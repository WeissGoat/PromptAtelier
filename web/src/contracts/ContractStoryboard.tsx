/**
 * 结果故事板（设计文档 §9「生图结果」第 2 点）：一份契约的全部出图，每帧一行按帧顺序排，
 * 右侧按「画风 · 时间」分轮列出结果；可按画风筛选、只看当前提示词、只看已采用。
 */
import { ArrowLeft, Play, Star } from "lucide-react";
import { useEffect, useMemo } from "react";

import { thumbUrl } from "../api/client";
import { NodePreviewImage } from "../components/NodePreviewImage";
import { TileSizeToggle } from "../components/TileSizeToggle";
import { tileSizes, type TileSize } from "../generation/tileSize";
import { frameMember } from "./analysis";
import type { ContractDetail, ContractFrame, ContractResultImage, ContractResults } from "./types";

export type BoardFilters = { artist: string; currentOnly: boolean; pickedOnly: boolean };

export const DEFAULT_BOARD_FILTERS: BoardFilters = { artist: "", currentOnly: false, pickedOnly: false };

/** 一轮：同一次提交（同一个结果目录）里同一个画风出的图。 */
export type ResultRound = { key: string; artist: string; run: string; startedAt: number; images: ContractResultImage[] };

const SIZE_LABELS: Record<string, string> = { portrait: "竖", landscape: "横", square: "方" };
const SUMMARY_CHARS = 220;

export function filterBoardImages(images: ContractResultImage[], filters: BoardFilters): ContractResultImage[] {
  return images.filter(
    (image) =>
      (!filters.artist || (image.artist ?? "") === filters.artist) &&
      (!filters.currentOnly || image.current) &&
      (!filters.pickedOnly || image.picked),
  );
}

/** 按「结果目录 + 画风」分轮；轮按最新出图时间倒序，轮内保持原顺序。 */
export function groupRounds(images: ContractResultImage[]): ResultRound[] {
  const rounds = new Map<string, ResultRound>();
  for (const image of images) {
    const artist = image.artist ?? "";
    const key = `${image.run}|${artist}`;
    const round = rounds.get(key) ?? { key, artist, run: image.run, startedAt: image.created_at, images: [] };
    round.startedAt = Math.min(round.startedAt, image.created_at);
    round.images.push(image);
    rounds.set(key, round);
  }
  const latest = (round: ResultRound) => Math.max(...round.images.map((image) => image.created_at));
  return [...rounds.values()].sort((a, b) => latest(b) - latest(a));
}

/** 契约结果里出现过的画风及张数，张数多的在前。 */
export function boardArtists(results: ContractResults | null): Array<{ name: string; count: number }> {
  const counts = new Map<string, number>();
  Object.values(results?.frames ?? {}).forEach((images) =>
    images.forEach((image) => counts.set(image.artist ?? "", (counts.get(image.artist ?? "") ?? 0) + 1)),
  );
  return [...counts.entries()].map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
}

export function roundCount(images: ContractResultImage[]): number {
  return new Set(images.map((image) => `${image.run}|${image.artist ?? ""}`)).size;
}

function formatTime(seconds: number): string {
  const date = new Date(seconds * 1000);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getMonth() + 1}/${date.getDate()} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function summary(text: string): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > SUMMARY_CHARS ? `${flat.slice(0, SUMMARY_CHARS)}…` : flat;
}

type Props = {
  detail: ContractDetail;
  results: ContractResults | null;
  filters: BoardFilters;
  tileSize: TileSize;
  /** 打开时滚到这一帧（从帧卡片的「查看全部」进来）。 */
  focusFrame: string | null;
  onFiltersChange(filters: BoardFilters): void;
  onTileSizeChange(size: TileSize): void;
  onFocusHandled(): void;
  onBack(): void;
  onGenerate(frameId: string): void;
  onOpenImage(frame: ContractFrame, images: ContractResultImage[], index: number): void;
  onTogglePick(image: ContractResultImage): void;
};

export function ContractStoryboard(props: Props) {
  const { detail, results, tileSize, focusFrame, onFocusHandled } = props;
  const artists = useMemo(() => boardArtists(results), [results]);
  // 记住的画风这份契约里没有时按「全部画风」处理。
  const filters = artists.some((item) => item.name === props.filters.artist) ? props.filters : { ...props.filters, artist: "" };
  const update = (patch: Partial<BoardFilters>) => props.onFiltersChange({ ...filters, ...patch });

  const all = Object.values(results?.frames ?? {}).flat();
  const framesWithImages = detail.frames.filter((frame) => (results?.frames[frame.id] ?? []).length).length;
  const pickedTotal = all.filter((image) => image.picked).length;

  useEffect(() => {
    if (!focusFrame) return;
    document.getElementById(`board-${focusFrame}`)?.scrollIntoView({ block: "start" });
    onFocusHandled();
  }, [focusFrame, onFocusHandled]);

  const tile = tileSizes[tileSize];
  const tileHeight = Math.round(tile.column * 1.25);

  return (
    <section aria-label="结果故事板" className="panel ct-board">
      <header className="ct-board-head">
        <button className="btn-sm" onClick={props.onBack} type="button"><ArrowLeft size={13} /> 返回契约</button>
        <div className="ct-head-title">
          <h2>结果故事板 · {detail.request.title || detail.id}</h2>
          <small className="muted">
            {detail.frames.length} 帧 · {framesWithImages} 帧有图 · 共 {all.length} 张{pickedTotal ? ` · 已采用 ${pickedTotal}` : ""}
            {results ? "" : " · 正在读取结果…"}
          </small>
        </div>
      </header>

      <div className="ct-toolbar ct-board-toolbar">
        <label className="ct-check">
          画风
          <select aria-label="按画风筛选" onChange={(event) => update({ artist: event.target.value })} value={filters.artist}>
            <option value="">全部画风</option>
            {artists.map((item) => (
              <option key={item.name} value={item.name}>{item.name || "（未记录画风）"} · {item.count}</option>
            ))}
          </select>
        </label>
        <label className="ct-check">
          <input checked={filters.currentOnly} onChange={(event) => update({ currentOnly: event.target.checked })} type="checkbox" /> 只看当前提示词
        </label>
        <label className="ct-check">
          <input checked={filters.pickedOnly} onChange={(event) => update({ pickedOnly: event.target.checked })} type="checkbox" /> 只看已采用
        </label>
        <span className="ct-board-spacer" />
        <TileSizeToggle onChange={props.onTileSizeChange} value={tileSize} />
      </div>

      <div className="ct-board-rows">
        {detail.frames.map((frame) => {
          const images = results?.frames[frame.id] ?? [];
          const shown = filterBoardImages(images, filters);
          const rounds = groupRounds(shown);
          const member = frameMember(frame, detail.sources);
          const reference = frame.inspired_by.map((ref) => detail.sources.references[ref]).find(Boolean) ?? null;
          const preview = member ?? reference;
          const positive = frame.submit.positive ?? frame.prompts.positive ?? "";
          const picked = images.filter((image) => image.picked).length;
          const current = images.filter((image) => image.current).length;
          return (
            <article className="ct-board-row" id={`board-${frame.id}`} key={frame.id}>
              <div className="ct-board-info">
                <div className="ct-board-info-head">
                  {preview ? (
                    <NodePreviewImage className="ct-frame-preview" name={preview.title} nodeRef={preview.path} size={160} />
                  ) : (
                    <span className="node-preview node-preview-empty ct-frame-preview" />
                  )}
                  <div>
                    <div>
                      <strong className="mono">{frame.id}</strong> <strong>{frame.title}</strong>
                    </div>
                    <div className="ct-row">
                      {frame.size ? <span className="chip">{SIZE_LABELS[frame.size] ?? frame.size}</span> : null}
                      {frame.characters.map((id) => <span className={`chip ct-char origin-${id}`} key={id}>{id}</span>)}
                    </div>
                    <small className="muted">
                      {images.length ? `${images.length} 张 · ${roundCount(images)} 轮 · 当前 ${current}${picked ? ` · 已采用 ${picked}` : ""}` : "还没有出图"}
                    </small>
                  </div>
                </div>
                <p className="ct-board-prompt" title={positive}>{summary(positive) || "（没有正向提示词）"}</p>
                <button className={images.length ? "btn-sm" : "btn-sm primary"} onClick={() => props.onGenerate(frame.id)} type="button">
                  <Play size={13} /> 生成此帧
                </button>
              </div>

              <div className="ct-board-results">
                {!images.length ? (
                  <p className="muted">还没有出图。</p>
                ) : !shown.length ? (
                  <p className="muted">没有符合筛选的图（共 {images.length} 张）。</p>
                ) : (
                  rounds.map((round) => (
                    <div className="ct-round" key={round.key}>
                      <div className="ct-round-head">
                        <strong>{round.artist || "（未记录画风）"}</strong>
                        <span className="muted"> · {formatTime(round.startedAt)} · {round.images.length} 张</span>
                      </div>
                      <div className="ct-round-tiles">
                        {round.images.map((image) => (
                          <figure className={`ct-result${image.current ? "" : " is-old"}${image.picked ? " is-picked" : ""}`} key={image.path}>
                            <button
                              aria-label={`查看 ${frame.id} ${round.artist} seed ${image.seed ?? "?"}`}
                              className="ct-result-image ct-board-image"
                              onClick={() => props.onOpenImage(frame, shown, shown.indexOf(image))}
                              style={{ height: tileHeight, maxWidth: tile.column * 1.6 }}
                              title={`${round.artist}${image.seed !== undefined && image.seed !== null ? ` · seed ${image.seed}` : ""}${image.current ? "" : " · 提示词已改"}`}
                              type="button"
                            >
                              <img alt="" loading="lazy" src={thumbUrl(image.path, tile.thumb)} />
                            </button>
                            <figcaption className="ct-board-caption">
                              <span className="mono">{image.seed ?? "—"}</span>
                              {image.current ? null : <span className="ct-old-tag">提示词已改</span>}
                            </figcaption>
                            <button
                              aria-label={image.picked ? "取消采用" : "采用"}
                              aria-pressed={image.picked}
                              className="ct-pick icon-button btn-sm"
                              onClick={() => props.onTogglePick(image)}
                              title={image.picked ? "取消采用" : "采用（每帧可采用多张）"}
                              type="button"
                            >
                              <Star size={12} />
                            </button>
                          </figure>
                        ))}
                      </div>
                    </div>
                  ))
                )}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
