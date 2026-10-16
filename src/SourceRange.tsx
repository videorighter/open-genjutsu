import { useRef, useState } from "react";
import type { Range } from "./workflow";

const tenth = (seconds: number) => Math.round(seconds * 10) / 10;

// 구간 of a 원본 영상, at 0.1 s precision. No range means the whole video.
export default function SourceRange({
  src,
  range,
  onChange,
}: {
  src: string;
  range?: Range;
  onChange: (range: Range | undefined) => void;
}) {
  const player = useRef<HTMLVideoElement>(null);
  const [total, setTotal] = useState(0);
  const start = range?.start ?? 0;
  const end = range?.end ?? total;
  function set(nextStart: number, nextEnd: number) {
    const s = tenth(Math.max(0, nextStart));
    const e = tenth(Math.min(total, nextEnd));
    if (!(s < e)) return; // A 구간 starts before it ends.
    onChange(s === 0 && e === total ? undefined : { start: s, end: e });
  }
  const now = () => player.current?.currentTime ?? 0;
  return (
    <>
      <video
        ref={player}
        className="asset-preview"
        src={src}
        controls
        onLoadedMetadata={(e) => setTotal(tenth(e.currentTarget.duration))}
      />
      {total > 0 && (
        <div className="source-range">
          <span className="field-label">
            구간
            <span>
              {(end - start).toFixed(1)}초 / 전체 {total.toFixed(1)}초
            </span>
          </span>
          <div className="source-range-row">
            <label>
              시작
              <input
                type="number"
                aria-label="구간 시작"
                min={0}
                max={end}
                step={0.1}
                value={start}
                onChange={(e) => set(Number(e.target.value), end)}
              />
            </label>
            <label>
              끝
              <input
                type="number"
                aria-label="구간 끝"
                min={start}
                max={total}
                step={0.1}
                value={end}
                onChange={(e) => set(start, Number(e.target.value))}
              />
            </label>
          </div>
          <div className="source-range-row">
            <button
              className="button secondary"
              onClick={() => set(now(), end)}
            >
              여기를 시작으로
            </button>
            <button
              className="button secondary"
              onClick={() => set(start, now())}
            >
              여기를 끝으로
            </button>
          </div>
          {range && (
            <button
              className="button secondary"
              onClick={() => onChange(undefined)}
            >
              전체 사용
            </button>
          )}
        </div>
      )}
    </>
  );
}
