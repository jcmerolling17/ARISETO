// frontend/public/js/utils/saved-farm.js

import { farms } from '../api/client.js';
import { loadJSON, removeJSON, saveJSON } from './store.js';

/** True for a farm saved by login or farm setup: a positive whole farm_id. */
export function isSavedFarm(farm) {
  return Number.isInteger(farm?.farm_id) && farm.farm_id > 0;
}

/**
 * The farm remembered on this device. When it is missing or not a real farm (a farm_id of 0
 * left by an earlier version of the app), the member's first farm is looked up again with
 * GET /farms and remembered, so no screen ever asks for a farm that doesn't exist.
 * Resolves to null when the member has no farm yet.
 */
export async function savedFarm() {
  const saved = loadJSON('farm');
  if (isSavedFarm(saved)) return saved;
  const list = await farms.list();
  const first = Array.isArray(list) ? list[0] ?? null : null;
  if (!first) {
    removeJSON('farm');
    return null;
  }
  const farm = {
    farm_id: first.farm_id,
    farm_name: first.farm_name,
    barangay_name: first.barangay_name,
    municipality: first.municipality,
  };
  saveJSON('farm', farm);
  return farm;
}
