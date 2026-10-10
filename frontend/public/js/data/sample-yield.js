// frontend/public/js/data/sample-yield.js

/**
 * Sample yield estimates (YIELD_ESTIMATE) for each field's current cycle, oldest first.
 * input_features is the snapshot of model inputs; its keys are sample names (the data
 * dictionary only says "area, variety, fertilizer kg, rainfall mm, etc."). The farm-gate prices
 * turn predicted_total_t into the expected value shown here and on the Crop Calendar.
 *
 * Field A (corn): 6.75 → 6.50 → 6.25 t; the latest drop follows the leaf blight found by the
 * sample scan. Field B (rice): 7.20 → 6.90 → 6.75 t.
 */

const HOUR = 60 * 60 * 1000;
const DAY = 24 * HOUR;

function ago(ms) {
  return new Date(Date.now() - ms).toISOString();
}

function estimate(id, cycleId, createdAt, yieldTHa, areaHa, features) {
  return {
    estimate_id: id,
    cycle_id: cycleId,
    requested_by: 6,
    input_features: { area_planted_ha: areaHa, ...features },
    predicted_yield_t_ha: yieldTHa,
    predicted_total_t: Math.round(yieldTHa * areaHa * 100) / 100,
    model_version: 'demo-0.1',
    created_at: createdAt,
  };
}

export const sampleYield = {
  farmgate_prices: [
    { crop_name: 'Corn', price_php_per_kg: 18 },
    { crop_name: 'Rice', price_php_per_kg: 20 },
  ],
  estimates: [
    // Field A: corn, planted 23 days ago
    estimate(11, 101, ago(23 * DAY), 5.4, 1.25, {
      days_after_planting: 0, seed_kg: 18, seed_type: 'hybrid', fertilizer_sacks: 4, rainfall_mm: 0, crop_health: 'healthy', soil_type: 'loam',
    }),
    estimate(12, 101, ago(9 * DAY), 5.2, 1.25, {
      days_after_planting: 14, seed_kg: 18, seed_type: 'hybrid', fertilizer_sacks: 7, rainfall_mm: 180, crop_health: 'healthy', soil_type: 'loam',
    }),
    estimate(13, 101, ago(1 * HOUR), 5.0, 1.25, {
      days_after_planting: 23, seed_kg: 18, seed_type: 'hybrid', fertilizer_sacks: 7, rainfall_mm: 240, crop_health: 'leaf_blight', soil_type: 'loam',
    }),
    // Field B: rice, transplanted 40 days ago
    estimate(21, 102, ago(40 * DAY), 4.8, 1.5, {
      days_after_planting: 0, seed_kg: 80, seed_type: 'certified', fertilizer_sacks: 0, rainfall_mm: 0, crop_health: 'healthy', soil_type: 'clay',
    }),
    estimate(22, 102, ago(19 * DAY), 4.6, 1.5, {
      days_after_planting: 21, seed_kg: 80, seed_type: 'certified', fertilizer_sacks: 4, rainfall_mm: 230, crop_health: 'healthy', soil_type: 'clay',
    }),
    estimate(23, 102, ago(2 * DAY), 4.5, 1.5, {
      days_after_planting: 38, seed_kg: 80, seed_type: 'certified', fertilizer_sacks: 4, rainfall_mm: 410, crop_health: 'healthy', soil_type: 'clay',
    }),
  ],
};

export const emptyYield = {
  farmgate_prices: [],
  estimates: [],
};
