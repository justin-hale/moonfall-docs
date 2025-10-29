import React from 'react';
import Link from '@docusaurus/Link';
import sessionsData from '@site/src/data/sessions.json';

interface SessionData {
  title: string;
  href: string;
  id: string;
  number: number;
}

interface SessionsData {
  sessions: SessionData[];
  interludes: SessionData[];
}

const SessionsList: React.FC = () => {
  const { sessions, interludes } = sessionsData as SessionsData;

  return (
    <div>
      <h2>Latest Sessions</h2>
      
      <h3>Main Sessions</h3>
      <ul>
        {sessions.map((session) => (
          <li key={session.id}>
            <Link to={session.href}>{session.title}</Link>
          </li>
        ))}
      </ul>
      
      {interludes.length > 0 && (
        <>
          <h3>Interludes</h3>
          <ul>
            {interludes.map((interlude) => (
              <li key={interlude.id}>
                <Link to={interlude.href}>{interlude.title}</Link>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
};

export default SessionsList;