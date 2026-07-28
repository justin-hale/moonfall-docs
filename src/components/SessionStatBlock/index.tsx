import React from 'react';
import statsData from '@site/data/session-stats.json';
import type {SessionRecord, SessionStatsData} from '@site/src/types/sessionStats';
import styles from './styles.module.css';

const data = statsData as unknown as SessionStatsData;

function formatDuration(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.round((seconds % 3600) / 60);
  return hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m`;
}

interface Props {
  /** Docusaurus doc id, e.g. "sessions/session-57" */
  docId: string;
}

const SessionStatBlock: React.FC<Props> = ({docId}) => {
  const sessionId = docId.split('/').pop();
  const session: SessionRecord | undefined = data.sessions.find(
    (s) => s.id === sessionId,
  );

  if (!session) {
    return null;
  }

  const hasStats = session.has_transcript;
  const hasAttendance = !!session.players_present?.length;
  if (!hasStats && !hasAttendance) {
    return null;
  }

  const pcs = session.speakers.filter((s) => s.role !== 'guest');
  const topNpcs = Object.entries(session.mentions.npcs).slice(0, 3);
  const maxShare = Math.max(...pcs.map((s) => s.word_share), 0.01);

  return (
    <div className={styles.statBlock}>
      <div className={styles.header}>
        <span className={styles.title}>Session by the numbers</span>
        {hasStats && session.duration_seconds != null && (
          <span className={styles.headerFacts}>
            {session.timing_quality === 'approx' ? '~' : ''}
            {formatDuration(session.duration_seconds)}
            {session.word_count != null &&
              ` · ${session.word_count.toLocaleString()} words`}
            {session.fun.nat20_mentions > 0 &&
              ` · ${session.fun.nat20_mentions} nat-20 mention${
                session.fun.nat20_mentions === 1 ? '' : 's'
              }`}
          </span>
        )}
      </div>

      {hasAttendance && (
        <div className={styles.row}>
          <span className={styles.label}>At the table</span>
          <span className={styles.chips}>
            {session.players_present!.map((name) => (
              <span key={name} className={styles.chip}>
                {name}
              </span>
            ))}
          </span>
        </div>
      )}

      {hasStats && pcs.length > 0 && (
        <div className={styles.row}>
          <span className={styles.label}>Talk share</span>
          <div className={styles.bars}>
            {pcs.map((s) => (
              <div key={s.name} className={styles.barRow}>
                <span className={styles.barName}>{s.name}</span>
                <div className={styles.barTrack}>
                  <div
                    className={s.role === 'dm' ? styles.barFillDm : styles.barFill}
                    style={{width: `${(s.word_share / maxShare) * 100}%`}}
                  />
                </div>
                <span className={styles.barValue}>
                  {Math.round(s.word_share * 100)}%
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {hasStats && topNpcs.length > 0 && (
        <div className={styles.row}>
          <span className={styles.label}>Talked about</span>
          <span className={styles.mentions}>
            {topNpcs.map(([name, count]) => (
              <span key={name} className={styles.mention}>
                {name} ×{count}
              </span>
            ))}
          </span>
        </div>
      )}
    </div>
  );
};

export default SessionStatBlock;
