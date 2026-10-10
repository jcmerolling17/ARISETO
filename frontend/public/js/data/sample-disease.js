// frontend/public/js/data/sample-disease.js

/**
 * Sample disease detection: one DISEASE row with its ordered TREATMENT steps, and three sample
 * DIAGNOSIS results (diseased, healthy, unrecognized) for a scan of Field A (corn).
 * Not in the data dictionary yet: DISEASE.description and DISEASE.why_it_matters (the text
 * shown on the result), and the retake / healthy tips.
 *
 * The disease text is sample content for the prototype; have it checked against the DA or
 * PhilRice guide MPMPC uses before release.
 */

const SOURCE = 'CIMMYT Maize Doctor, "Northern corn leaf blight"';

export const sampleDisease = {
  diseases: [
    {
      disease_id: 1,
      crop_name: 'Corn',
      disease_name: 'Northern Corn Leaf Blight',
      local_name: null,
      model_class_label: 'corn_northern_leaf_blight',
      pathogen_type: 'fungal',
      description: 'Northern corn leaf blight is a fungal disease caused by Exserohilum turcicum. '
        + 'Its spores spread by wind and rain splash during long periods of leaf wetness, and the '
        + 'lesions destroy the leaf area the plant needs to fill its grain.',
      symptoms: [
        'Long, cigar-shaped lesions, gray-green to tan, about 2.5–15 cm long',
        'Lesions start on the lower leaves, then spread upward',
        'Dark gray spores on the lesions in humid weather',
        'Large dead areas on the leaves in severe cases',
      ],
      why_it_matters: 'If the leaves above the ear are blighted before or soon after tasseling, '
        + 'grain filling suffers and yield can drop by 30% or more. Acting early protects those upper leaves.',
      treatments: [
        {
          step_no: 1,
          treatment_type: 'cultural',
          instruction_en: 'Scout the field every 3–4 days and check whether lesions are moving up to the leaves near the ear.',
          instruction_fil: null,
          source_reference: SOURCE,
        },
        {
          step_no: 2,
          treatment_type: 'chemical',
          instruction_en: 'If lesions reach the third leaf below the ear before tasseling, spray a fungicide registered for corn leaf blight at the label rate.',
          instruction_fil: null,
          source_reference: SOURCE,
        },
        {
          step_no: 3,
          treatment_type: 'cultural',
          instruction_en: 'After harvest, plow under or remove the crop residue, since the fungus survives on it.',
          instruction_fil: null,
          source_reference: SOURCE,
        },
        {
          step_no: 4,
          treatment_type: 'preventive',
          instruction_en: 'Next season, plant a resistant hybrid and rotate with a crop other than corn, such as rice or onion.',
          instruction_fil: null,
          source_reference: SOURCE,
        },
      ],
    },
  ],
  // DIAGNOSIS results the prototype can show; confidence below 0.70 is 'unrecognized'.
  results: {
    diseased: {
      diagnosis_id: 501,
      disease_id: 1,
      predicted_label: 'corn_northern_leaf_blight',
      confidence: 0.9134,
      result_status: 'diseased',
      model_version: 'demo-0.1',
    },
    healthy: {
      diagnosis_id: 502,
      disease_id: null,
      predicted_label: 'healthy',
      confidence: 0.9521,
      result_status: 'healthy',
      model_version: 'demo-0.1',
    },
    unrecognized: {
      diagnosis_id: 503,
      disease_id: null,
      predicted_label: 'corn_northern_leaf_blight',
      confidence: 0.4812,
      result_status: 'unrecognized',
      model_version: 'demo-0.1',
    },
  },
  healthy_tips: [
    'Keep scouting your field every week.',
    'Check the undersides of the leaves, where pests often hide.',
    'Scan again if you see spots, streaks, or yellowing.',
  ],
  retake_tips: [
    'Take the photo in daylight, out of harsh direct sun.',
    'Fill the frame with one leaf and keep the affected spots in view.',
    'Hold the phone steady so the photo is not blurry.',
    'Only rice, corn, and onion leaves can be checked.',
  ],
};

export const emptyDisease = {
  diseases: [],
  results: {},
  healthy_tips: [],
  retake_tips: [],
};
