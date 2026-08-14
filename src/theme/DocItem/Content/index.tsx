import React from 'react';
import Content from '@theme-original/DocItem/Content';
import type ContentType from '@theme/DocItem/Content';
import type {WrapperProps} from '@docusaurus/types';
import {useDoc} from '@docusaurus/plugin-content-docs/client';
import SessionStatBlock from '@site/src/components/SessionStatBlock';

type Props = WrapperProps<typeof ContentType>;

// Injects the session stat block above every session/interlude recap without
// editing the markdown files themselves (covers future sessions automatically).
export default function ContentWrapper(props: Props): React.ReactElement {
  const {metadata} = useDoc();
  const isSessionDoc = metadata.id.startsWith('sessions/');

  return (
    <>
      {isSessionDoc && <SessionStatBlock docId={metadata.id} />}
      <Content {...props} />
    </>
  );
}
