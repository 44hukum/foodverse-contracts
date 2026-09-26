import { useCallback, useEffect, useRef } from 'react';
import SignatureCanvas from 'react-signature-canvas';
import { exportSignaturePng } from './signing';

interface SignaturePadProps {
  /** Called with a PNG data URL after every stroke, or `null` when the pad is empty. */
  onChange: (dataUrl: string | null) => void;
  disabled?: boolean;
}

/** Sizes the backing store to the CSS box × device pixel ratio, as react-signature-canvas does on mount. */
function fitCanvasToBox(canvas: HTMLCanvasElement): void {
  const ratio = Math.max(window.devicePixelRatio || 1, 1);
  canvas.width = Math.max(1, Math.floor(canvas.offsetWidth * ratio));
  canvas.height = Math.max(1, Math.floor(canvas.offsetHeight * ratio));
  canvas.getContext('2d')?.scale(ratio, ratio);
}

/**
 * Drawn-signature input on top of react-signature-canvas. The canvas fills its
 * container so it works at 375px. Width changes (rotating a phone) redraw the
 * strokes instead of silently wiping them; height-only changes (mobile browser
 * toolbars) are ignored.
 */
export function SignaturePad({ onChange, disabled = false }: SignaturePadProps) {
  const padRef = useRef<SignatureCanvas>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const onChangeRef = useRef(onChange);

  useEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);

  const emit = useCallback((): void => {
    const pad = padRef.current;
    if (!pad || pad.isEmpty()) {
      onChangeRef.current(null);
      return;
    }
    onChangeRef.current(exportSignaturePng(pad.getCanvas()));
  }, []);

  function clear(): void {
    padRef.current?.clear();
    onChangeRef.current(null);
  }

  useEffect(() => {
    const pad = padRef.current;
    if (!pad) return;
    if (disabled) pad.off();
    else pad.on();
  }, [disabled]);

  useEffect(() => {
    const wrap = wrapRef.current;
    const pad = padRef.current;
    if (!wrap || !pad || typeof ResizeObserver === 'undefined') return;
    let lastWidth = wrap.clientWidth;
    const observer = new ResizeObserver(() => {
      const width = wrap.clientWidth;
      if (width === lastWidth) return;
      lastWidth = width;
      const strokes = pad.toData();
      fitCanvasToBox(pad.getCanvas());
      pad.clear();
      if (strokes.length > 0) pad.fromData(strokes);
      emit();
    });
    observer.observe(wrap);
    return () => observer.disconnect();
  }, [emit]);

  return (
    <div className="signature-pad">
      <div ref={wrapRef} className="signature-canvas-wrap">
        <SignatureCanvas
          ref={padRef}
          penColor="#1c1f24"
          clearOnResize={false}
          onEnd={emit}
          canvasProps={{
            className: 'signature-canvas',
            role: 'img',
            'aria-label': 'Signature pad. Draw your signature here with your finger or mouse.',
          }}
        />
      </div>
      <div className="signature-pad-actions">
        <button type="button" className="button-secondary" onClick={clear} disabled={disabled}>
          Clear signature
        </button>
      </div>
    </div>
  );
}
