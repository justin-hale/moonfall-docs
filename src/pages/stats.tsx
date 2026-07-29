import React, {useState} from 'react';
import Layout from '@theme/Layout';
import Link from '@docusaurus/Link';
import statsData from '@site/data/session-stats.json';
import type {
  PersonalityAxis,
  SessionRecord,
  SessionStatsData,
} from '@site/src/types/sessionStats';
import PlayerCharacterSheet from '@site/src/components/PlayerCharacterSheet';
import styles from './stats.module.css';

const data = statsData as unknown as SessionStatsData;

const DRIFT_AXES: {key: PersonalityAxis; label: string}[] = [
  {key: 'chaos', label: 'Chaos'},
  {key: 'heroism', label: 'Heroism'},
  {key: 'comedy', label: 'Comedy'},
  {key: 'immersion', label: 'Immersion'},
  {key: 'strategy', label: 'Strategy'},
  {key: 'curiosity', label: 'Curiosity'},
];

// Fixed player palette, readable on light and dark grounds.
const PLAYER_COLORS: Record<string, string> = {
  Topher: '#8a8a8a',
  Silas: '#c0392b',
  Bru: '#27a06a',
  Elspeth: '#b7791f',
  Leliana: '#8e5bb5',
  Olivia: '#2f7fb8',
  Ohma: '#1f9e9e',
};
const FALLBACK_COLOR = '#d16ba5';

function DriftChart() {
  const [axis, setAxis] = useState<PersonalityAxis>('chaos');
  const scored = data.sessions.filter((s) => s.personality);
  if (scored.length < 2) {
    return null;
  }

  // Only chart players with enough scored sessions for a meaningful line.
  const players = Object.entries(data.aggregate.personality_by_player)
    .filter(([, p]) => p.sessions_scored >= 3)
    .map(([name]) => name);

  const width = 800;
  const height = 260;
  const pad = {top: 12, right: 12, bottom: 24, left: 28};
  const x = (i: number) =>
    pad.left + (i / (scored.length - 1)) * (width - pad.left - pad.right);
  const y = (score: number) =>
    pad.top + ((20 - score) / 19) * (height - pad.top - pad.bottom);

  return (
    <>
      <div className={styles.axisButtons} role="group" aria-label="Personality axis">
        {DRIFT_AXES.map((a) => (
          <button
            key={a.key}
            type="button"
            className={
              a.key === axis ? styles.axisButtonActive : styles.axisButton
            }
            onClick={() => setAxis(a.key)}>
            {a.label}
          </button>
        ))}
      </div>
      <div className={styles.driftLegend}>
        {players.map((name) => (
          <span key={name} className={styles.legendItem}>
            <span
              className={styles.legendDot}
              style={{background: PLAYER_COLORS[name] ?? FALLBACK_COLOR}}
            />
            {name}
          </span>
        ))}
      </div>
      <div className={styles.driftChartWrap}>
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className={styles.driftChart}
          role="img"
          aria-label={`${axis} score per player across sessions`}>
          {[5, 10, 15, 20].map((tick) => (
            <g key={tick}>
              <line
                x1={pad.left}
                x2={width - pad.right}
                y1={y(tick)}
                y2={y(tick)}
                className={styles.gridLine}
              />
              <text x={4} y={y(tick) + 4} className={styles.gridLabel}>
                {tick}
              </text>
            </g>
          ))}
          {players.map((name) => {
            const points = scored
              .map((s, i) => {
                const score = s.personality!.scores[name]?.[axis];
                return score != null ? {i, score, session: s} : null;
              })
              .filter(Boolean) as {i: number; score: number; session: SessionRecord}[];
            if (points.length < 2) {
              return null;
            }
            const color = PLAYER_COLORS[name] ?? FALLBACK_COLOR;
            return (
              <g key={name}>
                <polyline
                  fill="none"
                  stroke={color}
                  strokeWidth={2}
                  strokeLinejoin="round"
                  points={points.map((p) => `${x(p.i)},${y(p.score)}`).join(' ')}
                />
                {points.map((p) => (
                  <circle
                    key={p.session.id}
                    cx={x(p.i)}
                    cy={y(p.score)}
                    r={3}
                    fill={color}>
                    <title>
                      {`${name} — ${p.session.title} (${p.session.date}): ${p.score}`}
                    </title>
                  </circle>
                ))}
              </g>
            );
          })}
          <text
            x={pad.left}
            y={height - 6}
            className={styles.gridLabel}>
            {scored[0].date}
          </text>
          <text
            x={width - pad.right}
            y={height - 6}
            textAnchor="end"
            className={styles.gridLabel}>
            {scored[scored.length - 1].date}
          </text>
        </svg>
      </div>
    </>
  );
}

function formatHours(seconds: number): string {
  return `${(seconds / 3600).toFixed(1)}h`;
}

function StatTile({value, label}: {value: string; label: string}) {
  return (
    <div className={styles.tile}>
      <span className={styles.tileValue}>{value}</span>
      <span className={styles.tileLabel}>{label}</span>
    </div>
  );
}

function BarList({
  entries,
  suffix,
}: {
  entries: [string, number][];
  suffix?: string;
}) {
  const max = Math.max(...entries.map(([, v]) => v), 1);
  return (
    <div>
      {entries.map(([name, value]) => (
        <div key={name} className={styles.barRow}>
          <span className={styles.barName}>{name}</span>
          <div className={styles.barTrack}>
            <div
              className={styles.barFill}
              style={{width: `${(value / max) * 100}%`}}
            />
          </div>
          <span className={styles.barValue}>
            {value.toLocaleString()}
            {suffix}
          </span>
        </div>
      ))}
    </div>
  );
}

export default function StatsPage(): React.ReactElement {
  const [includeDm, setIncludeDm] = useState(true);
  const agg = data.aggregate;

  const speakerTotals = agg.speaker_totals.filter(
    (s) => includeDm || s.role !== 'dm',
  );
  const talkEntries: [string, number][] = speakerTotals.map((s) => [
    s.name,
    s.words,
  ]);

  const withTranscripts = data.sessions.filter((s) => s.has_transcript);
  const longest = [...withTranscripts].sort(
    (a, b) => (b.duration_seconds ?? 0) - (a.duration_seconds ?? 0),
  )[0];
  const wordiest = [...withTranscripts].sort(
    (a, b) => (b.word_count ?? 0) - (a.word_count ?? 0),
  )[0];

  // Attendance: sessions attended per character, over sessions with any data.
  const withAttendance = data.sessions.filter((s) => s.players_present?.length);
  const attendance: Record<string, number> = {};
  withAttendance.forEach((s) =>
    s.players_present!.forEach((name) => {
      attendance[name] = (attendance[name] ?? 0) + 1;
    }),
  );
  const attendanceEntries = Object.entries(attendance).sort(
    (a, b) => b[1] - a[1],
  );

  // Character sheets: players with personality data, ordered by words spoken.
  const wordsByName = new Map(agg.speaker_totals.map((s) => [s.name, s.words]));
  const sheets = Object.entries(agg.personality_by_player).sort(
    (a, b) => (wordsByName.get(b[0]) ?? 0) - (wordsByName.get(a[0]) ?? 0),
  );

  const maxDuration = Math.max(
    ...withTranscripts.map((s) => s.duration_seconds ?? 0),
    1,
  );

  return (
    <Layout
      title="Campaign Stats"
      description="Statistics from the Moonfall D&D campaign — talk time, personalities, and more.">
      <main className="container margin-vert--lg">
        <h1>Campaign Stats</h1>
        <p className={styles.intro}>
          Data mined from {agg.sessions_with_transcripts} session transcripts
          (of {agg.total_sessions} recorded sessions). Personality scores are
          judged per session by an AI referee against a fixed rubric — every
          score is backed by an actual quote from the table.{' '}
          <a href="/data/session-stats.csv" download>
            Download the raw data (CSV)
          </a>
          .
        </p>

        <div className={styles.tiles}>
          <StatTile value={`${agg.total_sessions}`} label="sessions & interludes" />
          <StatTile
            value={formatHours(agg.total_duration_seconds)}
            label="of recorded table time"
          />
          <StatTile
            value={agg.total_words.toLocaleString()}
            label="words spoken"
          />
          <StatTile
            value={`${agg.nat20_mentions}`}
            label="nat-20 mentions*"
          />
        </div>

        {sheets.length > 0 && (
          <>
            <h2>The Party, By Personality</h2>
            <p className={styles.sectionNote}>
              Six ability scores (1–20), averaged across every analyzed
              session. Yes, the DM gets a sheet too.
            </p>
            <div className={styles.sheetGrid}>
              {sheets.map(([name, personality]) => {
                const totals = agg.speaker_totals.find((s) => s.name === name);
                return (
                  <PlayerCharacterSheet
                    key={name}
                    name={name}
                    personality={personality}
                    totals={totals}
                    subtitle={
                      totals?.role === 'dm' ? 'Dungeon Master' : undefined
                    }
                  />
                );
              })}
            </div>
          </>
        )}

        <h2>Personality Drift</h2>
        <p className={styles.sectionNote}>
          How each score has moved session to session — hover a point for the
          session and exact value.
        </p>
        <DriftChart />

        <h2>Who Does the Talking?</h2>
        <label className={styles.toggle}>
          <input
            type="checkbox"
            checked={includeDm}
            onChange={(e) => setIncludeDm(e.target.checked)}
          />{' '}
          Include the DM
        </label>
        <BarList entries={talkEntries} suffix=" words" />

        <div className={styles.columns}>
          <div>
            <h2>Most-Mentioned NPCs</h2>
            <BarList entries={Object.entries(agg.top_npcs).slice(0, 10)} />
          </div>
          <div>
            <h2>Most-Visited Places (by mention)</h2>
            <BarList entries={Object.entries(agg.top_locations).slice(0, 10)} />
          </div>
        </div>

        <h2>Attendance</h2>
        <p className={styles.sectionNote}>
          Sessions at the table, out of {withAttendance.length} with attendance
          records.
        </p>
        <BarList entries={attendanceEntries} />

        <h2>Session Lengths</h2>
        <p className={styles.sectionNote}>
          Each bar is one recorded session, oldest to newest. Hover for
          details.
        </p>
        <div className={styles.timeline}>
          {withTranscripts.map((s: SessionRecord) => (
            <Link
              key={s.id}
              to={s.href}
              className={styles.timelineBar}
              title={`${s.title} (${s.date}) — ${Math.round(
                (s.duration_seconds ?? 0) / 60,
              )} min`}
              style={{
                height: `${((s.duration_seconds ?? 0) / maxDuration) * 100}%`,
              }}
            />
          ))}
        </div>

        <h2>Hall of Records</h2>
        <ul>
          {longest && (
            <li>
              <strong>Longest session:</strong>{' '}
              <Link to={longest.href}>{longest.title}</Link> —{' '}
              {formatHours(longest.duration_seconds ?? 0)} at the table
            </li>
          )}
          {wordiest && (
            <li>
              <strong>Talkiest session:</strong>{' '}
              <Link to={wordiest.href}>{wordiest.title}</Link> —{' '}
              {(wordiest.word_count ?? 0).toLocaleString()} words
            </li>
          )}
          <li>
            <strong>Most-discussed party member:</strong>{' '}
            {Object.keys(agg.top_pcs_mentioned)[0] ?? '—'} (
            {Object.values(agg.top_pcs_mentioned)[0]?.toLocaleString() ?? 0}{' '}
            mentions)
          </li>
          <li>
            <strong>Nat-1 mentions:</strong> {agg.nat1_mentions}
          </li>
        </ul>

        <p className={styles.footnote}>
          * Counted from the transcripts, which capture dice talk imperfectly —
          treat roll stats as folklore, not forensics. Data covers transcripts
          from {withTranscripts[0]?.date} onward; earlier sessions predate
          recording.
        </p>
      </main>
    </Layout>
  );
}
