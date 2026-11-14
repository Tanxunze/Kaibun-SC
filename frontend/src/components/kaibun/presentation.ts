import type { Background, Scene, Wardrobe } from "./api";

/** Derive a frame from saved events so seeking backward is identical to replaying it. */
export function scenePresentation(scene: Scene, lineId: string): { wardrobe: Record<string, Wardrobe>; background: Background | null } {
  const wardrobe = { ...scene.wardrobe };
  let background = scene.background_asset ?? null;
  for (const line of scene.lines) {
    Object.assign(wardrobe, scene.wardrobe_changes?.[line.id]);
    if (scene.background_change_assets && Object.hasOwn(scene.background_change_assets, line.id)) background = scene.background_change_assets[line.id];
    if (line.id === lineId) break;
  }
  return { wardrobe, background };
}
