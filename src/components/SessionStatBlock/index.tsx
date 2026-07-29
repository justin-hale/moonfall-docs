import React from 'react';
import statBlocksData from '@site/data/session-stat-blocks.json';
import type {StatBlockRecord, StatBlocksData} from '@site/src/types/sessionStats';
import styles from './styles.module.css';

const data = statBlocksData as unknown as StatBlocksData;

function formatDuration(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.round((seconds % 3600) / 60);
  return hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m`;
}

interface Props {
  /** Docusaurus doc id, e.g. "sessions/session-57" */
  docId: string;
}

const SUPERLATIVE_LABELS: {key: 'mvp' | 'best_joke' | 'most_chaotic'; label: string}[] = [
  {key: 'mvp', label: 'MVP'},
  {key: 'best_joke', label: 'Best joke'},
  {key: 'most_chaotic', label: 'Most chaotic'},
];

const SessionStatBlock: React.FC<Props> = ({docId}) => {
  const sessionId = docId.split('/').pop() ?? '';
  const session: StatBlockRecord | undefined = data.blocks[sessionId];

  if (!session) {
    return null;
  }

  const hasStats = session.speakers.length > 0;
  const hasAttendance = !!session.players_present?.length;
  if (!hasStats && !hasAttendance) {
    return null;
  }

  const pcs = session.speakers.filter((s) => s.role !== 'guest');
  const topNpcs = Object.entries(session.top_npcs);
  const maxShare = Math.max(...pcs.map((s) => s.word_share), 0.01);
  const superlatives = SUPERLATIVE_LABELS.filter(
    ({key}) => session.superlatives?.[key]?.player,
  );

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

      {superlatives.length > 0 && (
        <div className={styles.row}>
          <span className={styles.label}>Superlatives</span>
          <div className={styles.superlatives}>
            {superlatives.map(({key, label}) => {
              const entry = session.superlatives![key]!;
              return (
                <div key={key} className={styles.superlative}>
                  <strong>{label}:</strong> {entry.player}
                  {entry.quote && (
                    <span className={styles.superlativeQuote}>
                      {' '}
                      — “{entry.quote}”
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};

export default SessionStatBlock;
