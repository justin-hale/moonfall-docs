import React, {useState} from 'react';
import Layout from '@theme/Layout';
import Link from '@docusaurus/Link';
import statsData from '@site/data/session-stats.json';
import type {
  SessionRecord,
  SessionStatsData,
} from '@site/src/types/sessionStats';
import PlayerCharacterSheet from '@site/src/components/PlayerCharacterSheet';
import styles from './stats.module.css';

const data = statsData as unknown as SessionStatsData;

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
