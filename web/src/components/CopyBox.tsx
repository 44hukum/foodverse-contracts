import { useRef, useState } from 'react';

interface CopyBoxProps {
  value: string;
  label: string;
}

/**
 * Read-only text box with a copy button. Used for the signing link, which must
 * never be rendered as a navigable anchor (CLAUDE.md rule 6): an <a> would put
 * the token in browser history and referrer headers.
 */
export function CopyBox({ value, label }: CopyBoxProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle');

  async function copy(): Promise<void> {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(value);
      } else {
        inputRef.current?.select();
        if (!document.execCommand('copy')) throw new Error('copy command failed');
      }
      setState('copied');
    } catch {
      setState('failed');
      inputRef.current?.select();
    }
  }

  return (
    <div className="copy-box">
      <input
        ref={inputRef}
        type="text"
        readOnly
        value={value}
        aria-label={label}
        onFocus={(event) => event.currentTarget.select()}
        spellCheck={false}
        autoComplete="off"
      />
      <button type="button" onClick={() => void copy()}>
        Copy link
      </button>
      <span role="status" className="copy-status">
        {state === 'copied' && 'Copied to clipboard'}
        {state === 'failed' && 'Copy failed. Select the text and copy it manually.'}
      </span>
    </div>
  );
}
