from __future__ import absolute_import

from rest_framework.response import Response

from sentry import roles
from sentry.api.base import Endpoint
from sentry.api.exceptions import ResourceDoesNotExist, ProjectMoved
from sentry.auth.superuser import is_active_superuser
from sentry.auth.system import is_system_auth
from sentry.models import OrganizationMember, Project, ProjectStatus, ProjectRedirect
from sentry.utils.sdk import configure_scope

from .organization import OrganizationPermission
from .team import has_team_permission


class ProjectPermission(OrganizationPermission):
    scope_map = {
        "GET": ["project:read", "project:write", "project:admin"],
        "POST": ["project:write", "project:admin"],
        "PUT": ["project:write", "project:admin"],
        "DELETE": ["project:admin"],
    }

    def has_object_permission(self, request, view, project):
        result = super(ProjectPermission, self).has_object_permission(
            request, view, project.organization
        )

        if not result:
            return result
        if project.teams.exists():
            return any(
                has_team_permission(request, team, self.scope_map) for team in project.teams.all()
            )
        elif is_system_auth(request.auth):
            return True
        elif request.user.is_authenticated():
            # this is only for team-less projects
            if is_active_superuser(request):
                return True
            try:
                role = (
                    OrganizationMember.objects.filter(
                        organization=project.organization, user=request.user
                    )
                    .values_list("role", flat=True)
                    .get()
                )
            except OrganizationMember.DoesNotExist:
                # this should probably never happen?
                return False

            return roles.get(role).is_global
        elif hasattr(request.auth, "project_id") and project.id == request.auth.project_id:
            return True

        return False


class StrictProjectPermission(ProjectPermission):
    scope_map = {
        "GET": ["project:write", "project:admin"],
        "POST": ["project:write", "project:admin"],
        "PUT": ["project:write", "project:admin"],
        "DELETE": ["project:admin"],
    }


class ProjectReleasePermission(ProjectPermission):
    scope_map = {
        "GET": ["project:read", "project:write", "project:admin", "project:releases"],
        "POST": ["project:write", "project:admin", "project:releases"],
        "PUT": ["project:write", "project:admin", "project:releases"],
        "DELETE": ["project:admin", "project:releases"],
    }


class ProjectEventPermission(ProjectPermission):
    scope_map = {
        "GET": ["event:read", "event:write", "event:admin"],
        "POST": ["event:write", "event:admin"],
        "PUT": ["event:write", "event:admin"],
        "DELETE": ["event:admin"],
    }


class ProjectSettingPermission(ProjectPermission):
    scope_map = {
        "GET": ["project:read", "project:write", "project:admin"],
        "POST": ["project:write", "project:admin"],
        "PUT": ["project:write", "project:admin"],
        "DELETE": ["project:write", "project:admin"],
    }


class RelaxedSearchPermission(ProjectPermission):
    scope_map = {
        "GET": ["project:read", "project:write", "project:admin"],
        # members can do writes
        "POST": ["project:write", "project:admin", "project:read"],
        "PUT": ["project:write", "project:admin", "project:read"],
        # members can delete their own searches
        "DELETE": ["project:read", "project:write", "project:admin"],
    }


class ProjectEndpoint(Endpoint):
    permission_classes = (ProjectPermission,)

    def convert_args(self, request, organization_slug, project_slug, *args, **kwargs):
        try:
            project = (
                Project.objects.filter(organization__slug=organization_slug, slug=project_slug)
                .select_related("organization")
                .prefetch_related("teams")
                .get()
            )
        except Project.DoesNotExist:
            try:
                # Project may have been renamed
                redirect = ProjectRedirect.objects.select_related("project")
                redirect = redirect.get(
                    organization__slug=organization_slug, redirect_slug=project_slug
                )

                # get full path so that we keep query strings
                requested_url = request.get_full_path()
                new_url = requested_url.replace(
                    "projects/%s/%s/" % (organization_slug, project_slug),
                    "projects/%s/%s/" % (organization_slug, redirect.project.slug),
                )

                # Resource was moved/renamed if the requested url is different than the new url
                if requested_url != new_url:
                    raise ProjectMoved(new_url, redirect.project.slug)

                # otherwise project doesn't exist
                raise ResourceDoesNotExist
            except ProjectRedirect.DoesNotExist:
                raise ResourceDoesNotExist

        if project.status != ProjectStatus.VISIBLE:
            raise ResourceDoesNotExist

        self.check_object_permissions(request, project)

        with configure_scope() as scope:
            scope.set_tag("project", project.id)
            scope.set_tag("organization", project.organization_id)

        request._request.organization = project.organization

        kwargs["project"] = project
        return (args, kwargs)

    def handle_exception(self, request, exc):
        if isinstance(exc, ProjectMoved):
            response = Response(
                {"slug": exc.detail["detail"]["extra"]["slug"], "detail": exc.detail["detail"]},
                status=exc.status_code,
            )
            response["Location"] = exc.detail["detail"]["extra"]["url"]
            return response
        return super(ProjectEndpoint, self).handle_exception(request, exc)
