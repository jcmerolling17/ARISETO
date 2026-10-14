// frontend/public/js/data/sample-calendar.js

import { sampleFarm } from './sample-farm.js';
import { addDays, parseISODate, toISODate } from '../utils/dates.js';

/**
 * Sample crop calendar: CROP_ACTIVITY rows for each field's current cycle. "Expected value"
 * comes from the latest yield estimate in sample-yield.js.
 * growth_stage, start_time and reminder are not in the data dictionary yet.
 * Dates are counted from each cycle's planting date, so land preparation comes before it
 * and sowing falls on it.
 */

function plantedOn(cycleId) {
  return parseISODate(sampleFarm.cycles.find((c) => c.cycle_id === cycleId).planting_date);
}

/** One activity; `day` counts from the planting date, `done` marks it finished at its start time. */
function task(cycleId, id, day, stage, time, title, description, { done = false, reminder = 'none' } = {}) {
  const date = addDays(plantedOn(cycleId), day);
  const [hour, minute] = time.split(':').map(Number);
  const completed = new Date(date.getFullYear(), date.getMonth(), date.getDate(), hour, minute + 30);
  return {
    activity_id: id,
    cycle_id: cycleId,
    template_task_id: null,
    title,
    description,
    growth_stage: stage,
    scheduled_date: toISODate(date),
    start_time: time,
    reminder,
    status: done ? 'done' : 'pending',
    completed_at: done ? completed.toISOString() : null,
  };
}

const CORN = 101;
const RICE = 102;

export const sampleCalendar = {
  activities: [
    task(CORN, 1, -7, 'land_preparation', '07:00', 'Plow and harrow the field', 'Plow to 15–20 cm deep, then harrow to break up clods.', { done: true }),
    task(CORN, 2, -4, 'land_preparation', '07:00', 'Clear weeds and level the field', 'Remove weeds and level low spots so water drains evenly.', { done: true }),
    task(CORN, 3, -2, 'land_preparation', '08:00', 'Make furrows', 'Open furrows 75 cm apart for the planting rows.', { done: true }),
    task(CORN, 4, 0, 'seed_sowing', '06:00', 'Seed selection', 'Sort the seeds and set aside damaged or shriveled ones.', { done: true }),
    task(CORN, 5, 0, 'seed_sowing', '07:00', 'Planting', 'Sow 1–2 seeds per hill along the furrows.', { done: true }),
    task(CORN, 6, 0, 'seed_sowing', '16:00', 'Initial watering', 'Water the rows lightly after sowing.', { done: true }),
    task(CORN, 7, 7, 'vegetative', '07:00', 'Replant missing hills', 'Replant hills where no seedling came up.', { done: true }),
    task(CORN, 8, 14, 'vegetative', '07:00', 'First side-dress fertilizer', 'Apply fertilizer along the rows, then cover it with soil.', { done: true }),
    task(CORN, 9, 17, 'vegetative', '07:00', 'Hand weeding', 'Pull weeds between the rows while the soil is moist.', { done: true }),
    task(CORN, 10, 23, 'vegetative', '07:00', 'Check field water level', 'Walk the furrows and make sure the soil stays moist.', { done: true, reminder: '30_min' }),
    task(CORN, 11, 23, 'vegetative', '15:00', 'Scout for corn borers', 'Look for small holes and sawdust-like frass on the stalks.', { reminder: '30_min' }),
    task(CORN, 12, 24, 'vegetative', '08:00', 'Apply organic fertilizer', 'Side-dress around the base of the corn stalks before 9:00 AM.', { reminder: '1_hour' }),
    task(CORN, 13, 26, 'vegetative', '07:00', 'Remove dead lower leaves', 'Remove yellowing or blighted lower leaves to improve airflow.'),
    task(CORN, 14, 30, 'vegetative', '07:00', 'Second side-dress fertilizer', 'Apply the second split of fertilizer along the rows.', { reminder: '1_day' }),
    task(CORN, 15, 32, 'vegetative', '15:00', 'Scout for fall armyworm', 'Check the whorls for feeding damage and larvae.'),
    task(CORN, 16, 35, 'vegetative', '07:00', 'Hilling-up', 'Pile soil around the base of the plants to support the stalks.'),
    task(CORN, 17, 55, 'reproductive', '07:00', 'Check tasseling and silking', 'Note when most plants show tassels and silks.'),
    task(CORN, 18, 63, 'reproductive', '15:00', 'Scout for ear worms', 'Check the silks and ear tips for larvae.'),
    task(CORN, 19, 75, 'reproductive', '07:00', 'Irrigate during grain filling', 'Keep the soil moist while the kernels fill.', { reminder: '1_day' }),
    task(CORN, 20, 108, 'harvest', '07:00', 'Check grain moisture', 'Look for the black layer at the base of the kernels.'),
    task(CORN, 21, 115, 'harvest', '06:00', 'Harvest the ears', 'Harvest the ears once the husks are dry.', { reminder: '1_day' }),
    task(CORN, 22, 117, 'harvest', '07:00', 'Dry and shell the grains', 'Sun-dry the ears, then shell the grains.'),

    task(RICE, 31, -12, 'land_preparation', '07:00', 'Plow and puddle the paddy', 'Flood the paddy, then plow and puddle the soil.', { done: true }),
    task(RICE, 32, -4, 'land_preparation', '07:00', 'Level the paddy and fix the dikes', 'Level the field and patch the dikes to hold water.', { done: true }),
    task(RICE, 33, 0, 'seed_sowing', '06:00', 'Transplant seedlings', 'Transplant 2–3 seedlings per hill.', { done: true }),
    task(RICE, 34, 7, 'vegetative', '07:00', 'Replant missing hills', 'Fill in hills where seedlings died.', { done: true }),
    task(RICE, 35, 10, 'vegetative', '07:00', 'First fertilizer application', 'Broadcast the first split of fertilizer on the paddy.', { done: true }),
    task(RICE, 36, 25, 'vegetative', '07:00', 'Hand weeding', 'Pull weeds between the hills.', { done: true }),
    task(RICE, 37, 40, 'vegetative', '08:00', 'Maintain 3–5 cm water depth', 'Check the water level in Field B and adjust the inlet.', { reminder: '30_min' }),
    task(RICE, 38, 42, 'vegetative', '07:00', 'Second fertilizer application', 'Broadcast the second split of fertilizer.', { reminder: '1_day' }),
    task(RICE, 39, 55, 'reproductive', '15:00', 'Scout for stem borers', 'Look for dead hearts and whiteheads.'),
    task(RICE, 40, 70, 'reproductive', '07:00', 'Check panicle formation', 'Note when the panicles start to emerge.'),
    task(RICE, 41, 90, 'reproductive', '07:00', 'Drain the paddy', 'Drain the field about two weeks before harvest.', { reminder: '1_day' }),
    task(RICE, 42, 105, 'harvest', '06:00', 'Harvest the palay', 'Harvest when most grains are golden yellow.', { reminder: '1_day' }),
    task(RICE, 43, 107, 'harvest', '07:00', 'Dry the palay', 'Sun-dry the palay before storing or selling.'),
  ],
};

export const emptyCalendar = {
  activities: [],
};
