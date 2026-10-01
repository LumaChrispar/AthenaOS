```json
{
  "service_id": "SRV-028",
  "capability": "Voice Fingerprint Generation and Enforcement",
  "input_notes": {
    "genre_inference": "Dark political fantasy with gothic tragedy and an occult register.",
    "pov_inference": "Close third fixed on Edric Vane, selected to preserve subjective moral filtering, supernatural ambiguity, and the conflict between choice and fate.",
    "canonical_status": "The calibration scene is noncanonical and introduces no binding plot facts."
  },
  "outputs": [
    {
      "path": "08_Memory/voice_sample.md",
      "media_type": "text/markdown",
      "prose_word_count": 500,
      "word_count_method": "Whitespace-delimited words within the Calibration Prose section only.",
      "content": "# Voice Calibration Sample — The Witches of Wyrmwood Moor\n\n## Voice Parameters\n- **Sentence Length Profile**: Medium-default (12–22 words), with short punches (3–11 words) and accumulative long pressure (23–45 words). Structured sawtooth variation; never more than two consecutive sentences in one band. Fragments under three words are reserved for one climactic rupture per scene.\n- **Interiority-Action Ratio**: 40/60 — action, dialogue, and description lead; interiority arrives through brief free-indirect judgments, remembered motives, and sensory interpretation. At irreversible choices, interiority may rise to 50/50, but never becomes uninterrupted monologue.\n- **Adjective Policy**: Sparse (3–5%), chiefly sensory or categorical, with rare unsentimental evaluation. Maximum one adjective per noun phrase; no modifier chains.\n- **Metaphor Domain**: Moor ecology and decay crossed with military and court life, the body, and household craft: rain, seams, rot, orders, ledgers, wounds, splints, keys, and locks. Approximately one governing image per 50 words, compressed or implied. An image may extend for at most three sentences when exposing the bargain’s logic.\n- **Narrative Distance**: Close third fixed to Edric, filtered through his military habits, wounded pride, and need to convert choices into destiny. Free indirect discourse predominates. The camera never enters a witch’s mind; public ritual may widen briefly to collective reaction, then return to Edric’s perceptions.\n- **Tonal Register**: Cold, dry, fatalistic, and quietly acerbic; ceremonial during prophecy, plainer and quicker under threat, colder under grief. Irony turns inward against Edric, never toward the reader. Never cozy, whimsical, sentimental, mock-modern, slangy, or falsely grand; no faux-archaic dictionary words.\n\n## Calibration Prose (500 words)\n\nRain found the seams of Edric’s cloak and worked its way inward. He watched it darken the wool, one cold stitch at a time, while beyond the hall the eclipse turned the moor into a sallow lake. Every lantern had been ordered lit. Their flames leaned together as if listening.\n\nMerea brought the cup as though it were an office of state, both hands carefully supporting its silver stem. Poison was an ugly kind of loyalty. It asked the body to serve and left the mind to sign the order. He accepted; the stem warmed, gratitude following like final poison.\n\nAcross the chamber, Alaric wore his signet like a locked door; the crown suited him badly. So did mercy. Edric had confused one inconvenience with another. Edric expected the king to call him forward, ask why a captain had come armed to a feast, and learn the answer too late.\n\nHuldah watched from the deep shadow of the high stone seat. She had promised him justice, not truth, and the distinction had entered him by degrees, through blackthorn, wine, prophecy, the warm pressure of a friendly hand. Each gift had looked like a key, quietly opening another lock within him.\n\nHe could still turn. The thought was a narrow escape through a crowded room. He could spill the cup, name Merea, speak the charge aloud before the crown made his guilt official. Instead he imagined unpaid veterans; his resolve hardened around the old wound like a badly fitted iron splint.\n\nThe eclipse began without a sound. Huldah slowly raised her hand, and the room obeyed with the dull obedience of men uncertain which darkness had commanded them. She spoke of blood, a black sun, a crowned wolf. The words entered Edric as scripture enters a fever, entirely and too late.\n\nYsop smiled where torchlight failed. Merrin had placed false witnesses among the singers, lending them grief and rehearsed outrage. Edric called it fate because naming conspiracy would require movement. That was the witches’ deepest magic. They did not alter choices; they altered the air around refusal until it resembled doom.\n\nFootsteps struck the stair. The cup waited in his hand, its poison no heavier than rain. For one instant he imagined the king as a smaller man, frightened of the feast, unaware that the room had sharpened around his death. Then Alaric looked up, and Edric mistook recognition for command.\n\n\"Choose,\" the blackthorn said, though no voice had spoken, and Edric lifted the cup. Huldah’s face revealed neither joy nor warning. Prophecy gave her the stillness of a locked gate, and he mistook that stillness for consent. History would keep the moment, strip away cause, and call the murder his own.\n\nAt dawn the moor might keep its ledger, add his name, and send no answer. That was not prophecy. It was only moor, patient beneath rot and weather, keeping faith with no one. Huldah promised the land would remember. Edric mistook silence for consent because judgment was harder to bear."
    },
    {
      "event": "VoiceCalibrated",
      "payload": {
        "project_title": "The Witches of Wyrmwood Moor",
        "artifact_path": "08_Memory/voice_sample.md",
        "status": "ready_for_drafting",
        "voice_signature": "Cold, dry, fatalistic close third; action-led prose with compressed gothic and political imagery, inward irony, restrained ceremony, and fixed Edric-centered perception.",
        "enforcement_scope": [
          "SRV-005",
          "SRV-006",
          "SRV-027",
          "SRV-013"
        ]
      }
    }
  ],
  "validation": {
    "calibration_prose_word_count": 500,
    "required_word_count_range": {
      "minimum": 400,
      "maximum": 600
    },
    "all_six_parameters_defined": true,
    "sample_exercises_all_six_parameters": true,
    "consistent_with_outline_genre": true,
    "consistent_with_selected_pov": true,
    "binding_manuscript_prose": false
  }
}
```