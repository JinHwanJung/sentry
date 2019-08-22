import React from 'react';
import styled from 'react-emotion';

import LoadingMask from 'app/components/loadingMask';

const LoadingPanel = styled(props => (
  <div {...props}>
    <LoadingMask />
  </div>
))`
  flex: 1;
  flex-shrink: 0;
  overflow: hidden;
  height: 200px;
  position: relative;
  border-color: transparent;
  margin-bottom: 0;
`;

export default LoadingPanel;
