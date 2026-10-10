// frontend/public/js/data/sample-chatbot.js

/**
 * Sample chatbot: CHAT_INTENT rows, and one CHAT_SESSION with its CHAT_MESSAGE rows.
 * `patterns` are example phrases per intent, like the Keras intent model's training data; the
 * prototype matches typed words against them instead of running the model. They and `chip`
 * (the quick-question button) are not in the data dictionary. A message with intent_id null is
 * the fallback reply (confidence below the threshold).
 *
 * Answers match the other sample files: rain tomorrow 2–5 PM, northern corn leaf blight in
 * Field A, and Field A's 6.25-ton estimate. The source references are placeholders for the DA
 * or PhilRice guides MPMPC uses.
 */

const SAMPLE_SOURCE = 'Sample answer; replace with the DA or PhilRice guide';

function minutesAgo(minutes) {
  return new Date(Date.now() - minutes * 60 * 1000).toISOString();
}

export const sampleChatbot = {
  intents: [
    {
      intent_id: 1,
      intent_tag: 'greeting',
      crop_name: null,
      patterns: ['hello', 'hi', 'good morning', 'good afternoon', 'kumusta', 'magandang umaga'],
      response_en: 'Hello! I am your ARISETO Assistant. How can I help with your farm today?',
      response_fil: null,
      source_reference: SAMPLE_SOURCE,
      is_active: true,
    },
    {
      intent_id: 2,
      intent_tag: 'spray_timing',
      crop_name: null,
      patterns: ['should i spray', 'spray tomorrow', 'when to spray', 'mag-spray', 'spraying'],
      response_en: 'Rain is expected tomorrow from 2:00 PM to 5:00 PM. If you need to spray, do it early in the morning so it can dry before the rain. Would you like to see the forecast?',
      response_fil: null,
      source_reference: SAMPLE_SOURCE,
      is_active: true,
    },
    {
      intent_id: 3,
      intent_tag: 'weather_check',
      chip: 'Weather Check',
      crop_name: null,
      patterns: ['weather', 'rain', 'forecast', 'ulan', 'panahon', 'weather check'],
      response_en: 'Today in Tangkalan is partly sunny, around 30°C. Heavy rain is expected tomorrow from 2:00 PM to 5:00 PM, so finish fertilizer and spraying work in the morning.',
      response_fil: null,
      source_reference: SAMPLE_SOURCE,
      is_active: true,
    },
    {
      intent_id: 4,
      intent_tag: 'pest_advice',
      chip: 'Pest Advice',
      crop_name: 'Corn',
      patterns: ['pest', 'insect', 'borer', 'armyworm', 'worm', 'peste', 'pest advice'],
      response_en: 'For corn borers and fall armyworm, check the stalks and whorls every few days. Remove egg masses by hand, and spray only when damage is spreading, using an insecticide registered for corn at the label rate.',
      response_fil: null,
      source_reference: SAMPLE_SOURCE,
      is_active: true,
    },
    {
      intent_id: 5,
      intent_tag: 'yield_estimate',
      chip: 'Yield Estimate',
      crop_name: null,
      patterns: ['yield', 'harvest', 'tons', 'ani', 'how much will i harvest', 'yield estimate'],
      response_en: 'Your latest estimate for Field A (corn) is 6.25 tons, about 5.0 tons per hectare. Open Yield Estimation to see what affects it.',
      response_fil: null,
      source_reference: SAMPLE_SOURCE,
      is_active: true,
    },
    {
      intent_id: 6,
      intent_tag: 'disease_help',
      crop_name: 'Corn',
      patterns: ['disease', 'blight', 'spots', 'leaf', 'sakit', 'fungus'],
      response_en: 'Northern corn leaf blight was found in Field A. Scout every 3–4 days, and if lesions reach the third leaf below the ear before tasseling, spray a fungicide registered for corn leaf blight. Tap the camera button to scan another leaf.',
      response_fil: null,
      source_reference: SAMPLE_SOURCE,
      is_active: true,
    },
  ],
  fallback: 'Sorry, I didn’t understand that. Try one of these topics:',
  session: { session_id: 1, user_id: 6, started_at: minutesAgo(6) },
  messages: [
    { message_id: 1, session_id: 1, sender: 'bot', message_text: 'Hello! I am your ARISETO Assistant. How can I help with your farm today?', intent_id: 1, confidence: null, created_at: minutesAgo(6) },
    { message_id: 2, session_id: 1, sender: 'user', message_text: 'Should I spray my corn tomorrow?', intent_id: null, confidence: null, created_at: minutesAgo(5) },
    { message_id: 3, session_id: 1, sender: 'bot', message_text: 'Rain is expected tomorrow from 2:00 PM to 5:00 PM. If you need to spray, do it early in the morning so it can dry before the rain. Would you like to see the forecast?', intent_id: 2, confidence: 0.8812, created_at: minutesAgo(5) },
    { message_id: 4, session_id: 1, sender: 'user', message_text: 'How much is a sack of fertilizer at the coop?', intent_id: null, confidence: null, created_at: minutesAgo(2) },
    { message_id: 5, session_id: 1, sender: 'bot', message_text: 'Sorry, I didn’t understand that. Try one of these topics:', intent_id: null, confidence: 0.3104, created_at: minutesAgo(2) },
  ],
};

export const emptyChatbot = {
  intents: sampleChatbot.intents,
  fallback: sampleChatbot.fallback,
  session: null,
  messages: [],
};
