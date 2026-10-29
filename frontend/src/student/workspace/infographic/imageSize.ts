/** The frame's inner height (max-h 32rem less its p-6 padding): at zoom 1 a portrait or
 * square infographic is fitted to it, a landscape one to the frame's width. */
const FIT_HEIGHT_REM = 29;

/** Image size at `zoom`: `width` is a share of the frame; `maxWidth` caps a tall
 * (portrait or square) image so all of it shows at zoom 1 (`ratio` = natural
 * width / height, unknown until the image has loaded). Zoom scales both. */
export function imageSize(
  zoom: number,
  ratio: number | null,
): { width: string; maxWidth?: string } {
  const width = `${zoom * 100}%`;
  if (!ratio) return { width };
  return { width, maxWidth: `${+(zoom * FIT_HEIGHT_REM * ratio).toFixed(3)}rem` };
}
