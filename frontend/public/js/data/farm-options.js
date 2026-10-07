// frontend/public/js/data/farm-options.js

/** The 11 Occidental Mindoro municipalities (users.municipality, BARANGAY.municipality). */
export const MUNICIPALITIES = [
  'Abra de Ilog',
  'Calintaan',
  'Looc',
  'Lubang',
  'Magsaysay',
  'Mamburao',
  'Paluan',
  'Rizal',
  'Sablayan',
  'San Jose',
  'Santa Cruz',
];

/** CROP_CYCLE.season */
export const SEASONS = [
  { value: 'wet', label: 'Wet season' },
  { value: 'dry', label: 'Dry season' },
];

/** Units the farmer may type an area in; values are stored in hectares. */
export const AREA_UNITS = [
  { value: 'ha', label: 'ha' },
  { value: 'sqm', label: 'm²' },
];

/**
 * Rough bounding box of Occidental Mindoro (including Lubang Island),
 * used to catch GPS readings taken away from the farm.
 */
export const PROVINCE_BOUNDS = { minLat: 12.0, maxLat: 14.0, minLon: 119.8, maxLon: 121.4 };
