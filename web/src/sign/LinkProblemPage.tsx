import { DualTime } from '../components/DualTime';
import type { LinkProblem } from './signing';

interface LinkProblemPageProps {
  problem: LinkProblem;
  /** Offered only for transient problems (rate limit, server or network error). */
  onRetry?: () => void;
}

interface Copy {
  title: string;
  body: string;
  atLabel?: string;
  retry: boolean;
}

function copyFor(problem: LinkProblem): Copy {
  switch (problem.kind) {
    case 'invalid':
      return {
        title: 'This signing link is not valid',
        body:
          'Check that you opened the complete link from your email or message. ' +
          'If it still does not work, ask the sender for a new link.',
        retry: false,
      };
    case 'expired':
      return {
        title: 'This signing link has expired',
        body: 'Ask the sender to send you a new link. Nothing has been signed.',
        atLabel: 'Expired',
        retry: false,
      };
    case 'used':
      return {
        title: 'This document has already been signed',
        body: 'A copy of the signed document was emailed to you. Check your inbox and spam folder.',
        atLabel: 'Signed',
        retry: false,
      };
    case 'cancelled':
      return {
        title: 'This contract has been cancelled',
        body: 'The sender cancelled this contract. Contact them if you think this is a mistake.',
        retry: false,
      };
    case 'rate_limited':
      return {
        title: 'Too many requests',
        body: 'Please wait a moment and try again.',
        retry: true,
      };
    case 'unavailable':
      return {
        title: 'Could not load the document',
        body: 'Your link is still valid. Try again in a moment.',
        retry: true,
      };
  }
}

export function LinkProblemPage({ problem, onRetry }: LinkProblemPageProps) {
  const copy = copyFor(problem);
  return (
    <section className="card sign-problem" aria-labelledby="problem-heading">
      <h1 id="problem-heading">{copy.title}</h1>
      {problem.kind === 'unavailable' && problem.message && (
        <p className="banner banner-error" role="alert">
          {problem.message}
        </p>
      )}
      <p>{copy.body}</p>
      {copy.atLabel && problem.at && (
        <p className="small">
          {copy.atLabel} <DualTime iso={problem.at} />
        </p>
      )}
      {copy.retry && onRetry && (
        <p>
          <button type="button" onClick={onRetry}>
            Try again
          </button>
        </p>
      )}
    </section>
  );
}
