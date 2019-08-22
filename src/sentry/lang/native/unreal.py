from __future__ import absolute_import
from symbolic import Unreal4Crash
from sentry.lang.native.minidump import MINIDUMP_ATTACHMENT_TYPE
from sentry.models import UserReport
from sentry.utils.safe import set_path, setdefault_path


def process_unreal_crash(payload, user_id, environment, event):
    """Initial processing of the event from the Unreal Crash Reporter data.
    Processes the raw bytes of the unreal crash by returning a Unreal4Crash"""

    event["environment"] = environment

    if user_id:
        # https://github.com/EpicGames/UnrealEngine/blob/f509bb2d6c62806882d9a10476f3654cf1ee0634/Engine/Source/Programs/CrashReportClient/Private/CrashUpload.cpp#L769
        parts = user_id.split("|", 2)
        login_id, epic_account_id, machine_id = parts + [""] * (3 - len(parts))
        event["user"] = {"id": login_id if login_id else user_id}
        if epic_account_id:
            set_path(event, "tags", "epic_account_id", value=epic_account_id)
        if machine_id:
            set_path(event, "tags", "machine_id", value=machine_id)
    return Unreal4Crash.from_bytes(payload)


def unreal_attachment_type(unreal_file):
    """Returns the `attachment_type` for the
    unreal file type or None if not recognized"""
    if unreal_file.type == "minidump":
        return MINIDUMP_ATTACHMENT_TYPE


def merge_apple_crash_report(apple_crash_report, event):
    event["platform"] = "native"

    timestamp = apple_crash_report.get("timestamp")
    if timestamp:
        event["timestamp"] = timestamp

    event["threads"] = []
    for thread in apple_crash_report["threads"]:
        crashed = thread.get("crashed")

        # We don't create an exception because an apple crash report can have
        # multiple crashed threads.
        event["threads"].append(
            {
                "id": thread.get("id"),
                "name": thread.get("name"),
                "crashed": crashed,
                "stacktrace": {
                    "frames": [
                        {
                            "instruction_addr": frame.get("instruction_addr"),
                            "package": frame.get("module"),
                            "lineno": frame.get("lineno"),
                            "filename": frame.get("filename"),
                        }
                        for frame in reversed(thread.get("frames", []))
                    ],
                    "registers": thread.get("registers") or None,
                },
            }
        )

        if crashed:
            event["level"] = "fatal"

    if event.get("level") is None:
        event["level"] = "info"

    metadata = apple_crash_report.get("metadata")
    if metadata:
        set_path(event, "contexts", "os", "raw_description", value=metadata.get("OS Version"))
        set_path(event, "contexts", "device", "model", value=metadata.get("Hardware Model"))

    # Extract referenced (not all loaded) images
    images = [
        {
            "type": "macho",
            "code_file": module.get("path"),
            "debug_id": module.get("uuid"),
            "image_addr": module.get("addr"),
            "image_size": module.get("size"),
            "arch": module.get("arch"),
        }
        for module in apple_crash_report.get("binary_images")
    ]
    event.setdefault("debug_meta", {})["images"] = images


def merge_unreal_context_event(unreal_context, event, project):
    """Merges the context from an Unreal Engine 4 crash
    with the given event."""
    runtime_prop = unreal_context.get("runtime_properties")
    if runtime_prop is None:
        return

    message = runtime_prop.pop("error_message", None)
    if message is not None:
        event["message"] = message

    username = runtime_prop.pop("username", None)
    if username is not None:
        set_path(event, "user", "username", value=username)

    memory_physical = runtime_prop.pop("memory_stats_total_physical", None)
    if memory_physical is not None:
        set_path(event, "contexts", "device", "memory_size", value=memory_physical)

    # Likely overwritten by minidump processing
    os_major = runtime_prop.pop("misc_os_version_major", None)
    if os_major is not None:  # i.e: Windows 10
        set_path(event, "contexts", "os", "name", value=os_major)

    gpu_brand = runtime_prop.pop("misc_primary_cpu_brand", None)
    if gpu_brand is not None:
        set_path(event, "contexts", "gpu", "name", value=gpu_brand)

    user_desc = runtime_prop.pop("user_description", None)
    if user_desc is not None:
        feedback_user = "unknown"
        if username is not None:
            feedback_user = username

        UserReport.objects.create(
            project=project,
            event_id=event["event_id"],
            name=feedback_user,
            email="",
            comments=user_desc,
        )

    # drop modules. minidump processing adds 'images loaded'
    runtime_prop.pop("modules", None)

    # add everything else as extra
    set_path(event, "contexts", "unreal", "type", value="unreal")
    event["contexts"]["unreal"].update(**runtime_prop)

    # add sdk info
    event["sdk"] = {
        "name": "sentry.unreal.crashreporter",
        "version": runtime_prop.pop("crash_reporter_client_version", "0.0.0"),
    }


def merge_unreal_logs_event(unreal_logs, event):
    setdefault_path(event, "breadcrumbs", "values", value=[])
    breadcrumbs = event["breadcrumbs"]["values"]

    for log in unreal_logs:
        message = log.get("message")
        if message:
            breadcrumbs.append(
                {
                    "timestamp": log.get("timestamp"),
                    "category": log.get("component"),
                    "message": message,
                }
            )
