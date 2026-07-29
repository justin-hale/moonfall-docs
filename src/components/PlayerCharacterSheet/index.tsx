import React from 'react';
import type {
  PersonalityAxis,
  PlayerPersonalityAggregate,
  SpeakerTotals,
} from '@site/src/types/sessionStats';
import styles from './styles.module.css';

const AXES: {key: PersonalityAxis; label: string}[] = [
  {key: 'chaos', label: 'Chaos'},
  {key: 'heroism', label: 'Heroism'},
  {key: 'comedy', label: 'Comedy'},
  {key: 'immersion', label: 'Immersion'},
  {key: 'strategy', label: 'Strategy'},
  {key: 'curiosity', label: 'Curiosity'},
];

function modifier(score: number): string {
  const mod = Math.floor((score - 10) / 2);
  return mod >= 0 ? `+${mod}` : `${mod}`;
}

interface Props {
  name: string;
  personality: PlayerPersonalityAggregate;
  totals?: SpeakerTotals;
  subtitle?: string;
}

const PlayerCharacterSheet: React.FC<Props> = ({
  name,
  personality,
  totals,
  subtitle,
}) => {
  const scored = AXES.filter((a) => personality.mean_scores[a.key] != null);
  const topAxis = scored.reduce(
    (best, a) =>
      (personality.mean_scores[a.key] ?? 0) >
      (best ? personality.mean_scores[best.key] ?? 0 : -1)
        ? a
        : best,
    null as (typeof AXES)[number] | null,
  );
  const signature = topAxis
    ? personality.signature_evidence[topAxis.key]
    : undefined;
  const counts = personality.superlative_counts;
  const honors: string[] = [];
  if (counts.mvp > 0) honors.push(`${counts.mvp}× session MVP`);
  if (counts.best_joke > 0) honors.push(`${counts.best_joke}× best joke`);
  if (counts.most_chaotic > 0) honors.push(`${counts.most_chaotic}× most chaotic`);
  if (counts.decision_driver > 0)
    honors.push(`${counts.decision_driver}× decision driver`);

  return (
    <div className={styles.sheet}>
      <div className={styles.nameplate}>
        <span className={styles.name}>{name}</span>
        {subtitle && <span className={styles.subtitle}>{subtitle}</span>}
      </div>

      <div className={styles.abilities}>
        {AXES.map((axis) => {
          const score = personality.mean_scores[axis.key];
          return (
            <div key={axis.key} className={styles.ability}>
              <span className={styles.abilityLabel}>{axis.label}</span>
              <span className={styles.abilityScore}>
                {score != null ? Math.round(score) : '—'}
              </span>
              <span className={styles.abilityMod}>
                {score != null ? modifier(Math.round(score)) : ''}
              </span>
            </div>
          );
        })}
      </div>

      {signature && topAxis && (
        <blockquote className={styles.quote}>
          “{signature.quote}”
          <span className={styles.quoteAttribution}>
            — peak {topAxis.label.toLowerCase()}, {signature.session}
          </span>
        </blockquote>
      )}

      {honors.length > 0 && (
        <div className={styles.honors}>{honors.join(' · ')}</div>
      )}

      <div className={styles.footer}>
        {personality.sessions_scored} session
        {personality.sessions_scored === 1 ? '' : 's'} analyzed
        {totals && (
          <>
            {' '}
            · {totals.words.toLocaleString()} words spoken · at the table for{' '}
            {totals.sessions} recorded session{totals.sessions === 1 ? '' : 's'}
          </>
        )}
      </div>
    </div>
  );
};

export default PlayerCharacterSheet;
