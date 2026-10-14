// frontend/public/js/data/sample-farm.js

import { isoDateFromToday } from '../utils/dates.js';

/**
 * Sample farm shared by the prototype screens: the farm, its fields (FIELD), and their crop
 * cycles (CROP_CYCLE): the current wet-season cycle of each field plus last dry season's
 * harvested ones. Dates are relative to today so the demo stays current. Replace with
 * GET /farms and the farm's fields and cycles when the backend has them.
 */
export const sampleFarm = {
  farm: {
    farm_id: 1,
    farm_name: 'MPMPC Farm',
    barangay_name: 'Tangkalan',
    municipality: 'Mamburao',
    total_area_ha: 2.75,
  },
  fields: [
    { field_id: 1, farm_id: 1, field_name: 'Field A', area_ha: 1.25 },
    { field_id: 2, farm_id: 1, field_name: 'Field B', area_ha: 1.5 },
  ],
  cycles: [
    {
      cycle_id: 101,
      field_id: 1,
      crop_name: 'Corn',
      season: 'wet',
      area_planted_ha: 1.25,
      planting_method: 'direct_seeding',
      planting_date: isoDateFromToday(-23),
      expected_harvest_date: isoDateFromToday(92),
      status: 'active',
    },
    {
      cycle_id: 102,
      field_id: 2,
      crop_name: 'Rice',
      season: 'wet',
      area_planted_ha: 1.5,
      planting_method: 'transplanting',
      planting_date: isoDateFromToday(-40),
      expected_harvest_date: isoDateFromToday(65),
      status: 'active',
    },
    {
      cycle_id: 91,
      field_id: 1,
      crop_name: 'Corn',
      season: 'dry',
      area_planted_ha: 1.25,
      planting_method: 'direct_seeding',
      planting_date: isoDateFromToday(-200),
      expected_harvest_date: isoDateFromToday(-85),
      actual_harvest_date: isoDateFromToday(-83),
      status: 'harvested',
    },
    {
      cycle_id: 92,
      field_id: 2,
      crop_name: 'Rice',
      season: 'dry',
      area_planted_ha: 1.5,
      planting_method: 'transplanting',
      planting_date: isoDateFromToday(-205),
      expected_harvest_date: isoDateFromToday(-100),
      actual_harvest_date: isoDateFromToday(-98),
      status: 'harvested',
    },
  ],
};

export const emptyFarm = {
  farm: null,
  fields: [],
  cycles: [],
};
