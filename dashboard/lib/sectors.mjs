/**
 * Sector and index pages: the compare chart's rebasing and the treemap's
 * layout. The sector figures themselves are worked out once, by the publisher
 * (workers/sectors.py), and read from R2.
 *
 * Kept free of React so `node --test` can exercise it directly.
 */

const finite = (value) => typeof value === "number" && Number.isFinite(value);

/**
 * Points rebased to percent change from the first one at or after `from`:
 * TradingView's compare scale, so series of any price level share an axis.
 *
 * @param {{time: string, value: number}[]} points ascending
 */
export function rebase(points, from) {
  const start = points.findIndex((point) => point.time >= from && point.value > 0);
  if (start === -1) return [];
  const base = points[start].value;
  return points.slice(start).map((point) => ({ time: point.time, value: (point.value / base - 1) * 100 }));
}

/**
 * Squarified treemap (Bruls, Huizing, van Wijk): tiles as close to square as
 * the sizes allow, largest first, filling `width` x `height`.
 *
 * Items with no positive size are left out; the caller lists them.
 *
 * @template {{size: number}} T
 * @param {T[]} items
 * @returns {Array<T & {x: number, y: number, w: number, h: number}>}
 */
export function squarify(items, width, height) {
  const sized = items.filter((item) => finite(item.size) && item.size > 0).sort((a, b) => b.size - a.size);
  const total = sized.reduce((sum, item) => sum + item.size, 0);
  if (!total || width <= 0 || height <= 0) return [];
  const scale = (width * height) / total;
  const out = [];
  let rect = { x: 0, y: 0, w: width, h: height };
  let row = [];

  const worst = (areas, side) => {
    const sum = areas.reduce((a, b) => a + b, 0);
    const max = Math.max(...areas);
    const min = Math.min(...areas);
    return Math.max((side * side * max) / (sum * sum), (sum * sum) / (side * side * min));
  };

  const place = (entries) => {
    const sum = entries.reduce((a, entry) => a + entry.area, 0);
    if (rect.w >= rect.h) {
      const w = sum / rect.h;
      let y = rect.y;
      for (const entry of entries) {
        const h = entry.area / w;
        out.push({ ...entry.item, x: rect.x, y, w, h });
        y += h;
      }
      rect = { x: rect.x + w, y: rect.y, w: rect.w - w, h: rect.h };
    } else {
      const h = sum / rect.w;
      let x = rect.x;
      for (const entry of entries) {
        const w = entry.area / h;
        out.push({ ...entry.item, x, y: rect.y, w, h });
        x += w;
      }
      rect = { x: rect.x, y: rect.y + h, w: rect.w, h: rect.h - h };
    }
  };

  for (const item of sized) {
    const entry = { item, area: item.size * scale };
    const side = Math.min(rect.w, rect.h);
    const areas = row.map((r) => r.area);
    if (!row.length || worst([...areas, entry.area], side) <= worst(areas, side)) {
      row.push(entry);
    } else {
      place(row);
      row = [entry];
    }
  }
  if (row.length) place(row);
  return out;
}
