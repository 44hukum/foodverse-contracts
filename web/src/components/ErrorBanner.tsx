import { errorMessage } from '../util/errors';

export function ErrorBanner({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <div role="alert" className="banner banner-error">
      {errorMessage(error)}
    </div>
  );
}
