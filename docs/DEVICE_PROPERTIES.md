# Dictionnaire des `DevicePropCode` et codes de contrôle — Sony A6700

**🌍 Langue : [English](DEVICE_PROPERTIES.en.md) · Français**

Correspondance **code PTP → nom symbolique** du protocole de contrôle à distance
(PTP standard + extension vendor Sony « SDIO ») du boîtier **ILCE-6700**.

**386 codes** au total. Les noms sont reproduits verbatim tels qu'ils apparaissent
comme identifiants de paramètres du protocole. Ce sont des **constantes de
protocole** : ce document ne contient aucun fichier ni extrait binaire du firmware.

## Comment lire ce tableau

- **0x50xx** — propriétés `DevicePropCode` standard PTP (ISO 15740).
- **0xD1xx / 0xD2xx** — propriétés vendor Sony (`GetExtDevicePropDesc` 0x9203,
  `GetExtDevicePropValue` 0x9204, `SetExtDevicePropValue` 0x9205).
- **0xD2Cx–0xD2Fx** — « boutons » / actions de déclenchement, actionnées via
  `ControlDevice` (0x9207). ⚠️ **Écriture** : non émises par `probe_a6700.py`.
- **0xD3xx** — codes de contrôle système (`ControlDevice`). ⚠️ **Écriture**.

> Un code présent ici ne signifie pas qu'il est exposé/activé sur ce boîtier :
> certaines entrées sont héritées de la plateforme et filtrées par capacité modèle.
> Se fier à `operations_supported` / `device_properties_supported` renvoyés par
> `GetDeviceInfo` / `GetAllExtDevicePropInfo` à l'exécution.

## Codes de référence les plus utiles

| Code | Nom | Catégorie |
|---|---|---|
| `0x5013` | `still_capture_mode` | mode Drive (single / continu / bracket) |
| `0xD211` | `aspect_ratio` | ratio d'image |
| `0xD241` | `file_format_movie` | format fichier film |
| `0xD242` | `recording_setting_movie` | réglage d'enregistrement film |
| `0xD2C1` | `s1_button` | demi-pression AF *(écriture)* |
| `0xD2C2` | `s2_button` | déclenchement photo *(écriture)* |
| `0xD2C8` | `movie_rec_button` | enregistrement vidéo *(écriture)* |

---

## Table complète

### Propriétés standard PTP (0x50xx)  (8 codes)

| Code | Nom symbolique |
|---|---|
| 0x5005 | `white_balance` |
| 0x5007 | `f_number` |
| 0x500A | `focus_mode` |
| 0x500B | `exposure_metering_mode` |
| 0x500C | `flash_mode` |
| 0x500E | `exposure_program_mode` |
| 0x5010 | `exposure_bias_compensation` |
| 0x5013 | `still_capture_mode` |

### Propriétés vendor Sony — plage 0xD1xx  (189 codes)

| Code | Nom symbolique |
|---|---|
| 0xD100 | `creative_look_sharpness` |
| 0xD101 | `creative_look_sharpness_range` |
| 0xD102 | `creative_look_clarity` |
| 0xD103 | `custom_look_image_style` |
| 0xD104 | `time_code_preset_reset_enable_status` |
| 0xD105 | `user_bit_preset_reset_enable_status` |
| 0xD106 | `sensor_cleaning_enable_status` |
| 0xD107 | `reset_picture_profile_enable_status` |
| 0xD108 | `reset_creative_look_enable_status` |
| 0xD109 | `proxy_record_setting` |
| 0xD10C | `stream_protocol` |
| 0xD10E | `video_stream_adaptive_rate_control` |
| 0xD10F | `video_stream_resolution_method` |
| 0xD110 | `video_stream_resolution_easy_way` |
| 0xD111 | `stream_url` |
| 0xD112 | `stream_port` |
| 0xD113 | `stream_cipher_type` |
| 0xD114 | `stream_cipher_key` |
| 0xD115 | `stream_stream_key` |
| 0xD116 | `stream_latency` |
| 0xD117 | `stream_ttl` |
| 0xD119 | `stream_status` |
| 0xD11F | `timelapse_countdown_interval_time` |
| 0xD120 | `recording_duration` |
| 0xD121 | `remote_eframing` |
| 0xD122 | `eframing_type` |
| 0xD123 | `eframing_command_version` |
| 0xD124 | `eframing_mode_auto` |
| 0xD125 | `eframing_effect_type` |
| 0xD126 | `eframing_effect_directdion` |
| 0xD127 | `eframing_speed_ptz` |
| 0xD128 | `touch_exposure_bias_compensation` |
| 0xD129 | `transferfiletohttpserver_request_max` |
| 0xD12A | `contentlistprotocolbuffers_version` |
| 0xD12B | `wifi_direct_mode_off_enable_status` |
| 0xD12D | `second_battery_remaining` |
| 0xD12E | `second_battery_level_indicator` |
| 0xD133 | `anti_flicker_shoot` |
| 0xD134 | `anti_flicker_shoot_icon_status` |
| 0xD14A | `ftp_transfer_still_quality_size` |
| 0xD14B | `ftp_proxy_transfer_target` |
| 0xD14C | `ftp_power_save` |
| 0xD14D | `iso_auto_min_shutter_speed_mode` |
| 0xD150 | `usb_power_supply` |
| 0xD151 | `interval_rec_movie_frame_rate` |
| 0xD152 | `interval_rec_movie_record_setting` |
| 0xD153 | `eframing_recording_image_crop` |
| 0xD154 | `eframing_hdmi_crop` |
| 0xD157 | `subject_recognition_in_af` |
| 0xD158 | `recognition_target` |
| 0xD159 | `right_left_eye_select` |
| 0xD15B | `long_exposure_nr` |
| 0xD15C | `high_iso_nr` |
| 0xD15D | `hlg_still_image` |
| 0xD15E | `color_space` |
| 0xD15F | `recording_media_still_image` |
| 0xD160 | `recording_media_movie` |
| 0xD161 | `auto_switch_media` |
| 0xD162 | `drive_mode_dial_hi_plus_in_electric_shutter` |
| 0xD163 | `drive_mode_dial_hi_in_electric_shutter` |
| 0xD164 | `drive_mode_dial_mid_in_electric_shutter` |
| 0xD165 | `drive_mode_dial_lo_in_electric_shutter` |
| 0xD166 | `bracket_order` |
| 0xD167 | `focus_bracket_order` |
| 0xD168 | `focus_bracket_exposure_lock_1st_img` |
| 0xD169 | `focus_bracket_interval_until_next_shot` |
| 0xD16A | `interval_rec_still_shooting_start_time` |
| 0xD16B | `interval_rec_still_shooting_interval` |
| 0xD16C | `interval_rec_still_number_of_shots` |
| 0xD16D | `interval_rec_still_ae_tracking_sensitivity` |
| 0xD16E | `interval_rec_still_shutter_type` |
| 0xD16F | `interval_rec_still_shoot_interval_priority` |
| 0xD170 | `e_front_curtain_shutter` |
| 0xD171 | `wind_noise_reduct` |
| 0xD172 | `audio_level_display` |
| 0xD173 | `auto_slow_shutter` |
| 0xD176 | `iso_auto_min_shutter_speed_manual` |
| 0xD177 | `iso_auto_min_shutter_speed_preset` |
| 0xD178 | `soft_skin_effect` |
| 0xD179 | `priority_set_in_af_s` |
| 0xD17A | `priority_set_in_af_c` |
| 0xD17B | `focus_magnification_time` |
| 0xD17C | `volume_settings` |
| 0xD17D | `auto_review` |
| 0xD17E | `audio_signals` |
| 0xD17F | `hdmi_resolution` |
| 0xD180 | `hdmi_output_rec_media_movie` |
| 0xD181 | `hdmi_output_resolution_movie` |
| 0xD182 | `hdmi_output_4k_set` |
| 0xD183 | `hdmi_output_raw` |
| 0xD184 | `hdmi_output_raw_setting` |
| 0xD185 | `hdmi_output_color_gamut_for_raw_out` |
| 0xD186 | `hdmi_output_time_code` |
| 0xD187 | `hdmi_output_rec_control` |
| 0xD188 | `hdmi_output_audio` |
| 0xD192 | `image_stabilization_steady_shot_adjust` |
| 0xD193 | `image_stabilization_steady_shot_focal_length` |
| 0xD194 | `camera_shake_status` |
| 0xD195 | `update_body_error_status` |
| 0xD196 | `embed_lut_file` |
| 0xD197 | `media_slot1_writing_state` |
| 0xD198 | `media_slot2_writing_state` |
| 0xD199 | `auto_ftp_transfer_target_movie` |
| 0xD19A | `ftp_transfer_target` |
| 0xD19C | `focus_driving_status` |
| 0xD19D | `zoom_driving_status` |
| 0xD1A2 | `lens_compensation_shading` |
| 0xD1A3 | `lens_compensation_chromatic_aberration` |
| 0xD1A4 | `lens_compensation_distortion` |
| 0xD1A5 | `lens_compensation_breathing` |
| 0xD1A6 | `focus_bracket_recording_folder` |
| 0xD1A7 | `release_without_lens` |
| 0xD1A8 | `release_without_card` |
| 0xD1A9 | `image_stabilization_framing_stabilizer` |
| 0xD1AA | `priority_set_in_awb` |
| 0xD1AB | `af_illuminator` |
| 0xD1AC | `aperture_drive_in_af` |
| 0xD1AD | `af_with_shutter` |
| 0xD1AE | `full_time_dmf` |
| 0xD1AF | `pre_af` |
| 0xD1B0 | `display_quality_finder_monitor` |
| 0xD1B1 | `audio_signals_volume` |
| 0xD1B2 | `control_for_hdmi` |
| 0xD1B3 | `anti_dust_shutter_when_power_off` |
| 0xD1B4 | `self_timer_status` |
| 0xD1B5 | `metered_manual_level` |
| 0xD1B6 | `iso_auto_min` |
| 0xD1B7 | `iso_auto_max` |
| 0xD1B8 | `face_eye_frame_display` |
| 0xD1B9 | `focus_map` |
| 0xD1BA | `af_in_focus_magnifier` |
| 0xD1BB | `camera_error_caution_status` |
| 0xD1BC | `system_error_caution_status` |
| 0xD1BD | `initial_focus_magnifier_still` |
| 0xD1BE | `remote_save_image_size` |
| 0xD1BF | `program_shift_status` |
| 0xD1C6 | `tracking_on_af_on_enable_status` |
| 0xD1C7 | `aps_c_super_35mm_shooting` |
| 0xD1C8 | `recording_file_number` |
| 0xD1C9 | `forced_file_number_reset_enable_status` |
| 0xD1CA | `recording_setting_file_name` |
| 0xD1CB | `recording_folder_format` |
| 0xD1CD | `write_copyright_info` |
| 0xD1CE | `set_photographer` |
| 0xD1CF | `set_copyright` |
| 0xD1D4 | `contents_info_list_enable_status_slot1` |
| 0xD1D5 | `contents_info_list_enable_status_slot2` |
| 0xD1D6 | `contents_info_list_regenerate_time_slot1` |
| 0xD1D7 | `contents_info_list_regenerate_time_slot2` |
| 0xD1D8 | `select_on_camera_transfer_contents_list_status` |
| 0xD1D9 | `select_on_camera_transfer_resource_status` |
| 0xD1DA | `post_view_transfer_resource_status` |
| 0xD1DB | `create_new_folder_still_enable_status` |
| 0xD1DC | `file_settings_title_name_settings` |
| 0xD1DD | `microphone_directivity` |
| 0xD1DE | `grid_line_display` |
| 0xD1DF | `product_showcase_set` |
| 0xD1E0 | `amount_of_defocus_setting` |
| 0xD1E1 | `cinematic_vlog_setting` |
| 0xD1E2 | `cinematic_vlog_look` |
| 0xD1E3 | `cinematic_vlog_mood` |
| 0xD1E4 | `cinematic_vlog_af_transition_speed` |
| 0xD1E5 | `face_priority_in_multi_metering` |
| 0xD1E6 | `subject_recognition_person_tracking_subject_shift_range` |
| 0xD1E7 | `subject_recognition_animal_bird_priority` |
| 0xD1E8 | `subject_recognition_animal_bird_detection_parts` |
| 0xD1E9 | `subject_recognition_animal_still_tracking_subject_shift_range` |
| 0xD1EA | `subject_recognition_animal_still_tracking_sensitivity` |
| 0xD1EB | `subject_recognition_animal_still_detection_sensitivity` |
| 0xD1EC | `subject_recognition_animal_still_detection_parts` |
| 0xD1ED | `subject_recognition_bird_tracking_subject_shift_range` |
| 0xD1EE | `subject_recognition_bird_tracking_sensitivity` |
| 0xD1EF | `subject_recognition_bird_detection_sensitivity` |
| 0xD1F0 | `subject_recognition_bird_detection_parts` |
| 0xD1F1 | `subject_recognition_insect_tracking_subject_shift_range` |
| 0xD1F2 | `subject_recognition_insect_tracking_sensitivity` |
| 0xD1F3 | `subject_recognition_insect_detection_sensitivity` |
| 0xD1F4 | `subject_recognition_car_train_tracking_subject_shift_range` |
| 0xD1F5 | `subject_recognition_car_train_tracking_sensitivity` |
| 0xD1F6 | `subject_recognition_car_train_detection_sensitivity` |
| 0xD1F7 | `subject_recognition_plane_tracking_subject_shift_range` |
| 0xD1F8 | `subject_recognition_plane_tracking_sensitivity` |
| 0xD1F9 | `subject_recognition_plane_detection_sensitivity` |
| 0xD1FA | `subject_recognition_priority_on_registered_face` |
| 0xD1FB | `monitor_brightness_type` |
| 0xD1FC | `monitor_brightness_manual` |
| 0xD1FD | `tc_ub_display_setting` |
| 0xD1FE | `gamma_display_assist` |
| 0xD1FF | `gamma_display_assist_type` |

### Propriétés vendor Sony — plage 0xD2xx (hors « boutons »)  (136 codes)

| Code | Nom symbolique |
|---|---|
| 0xD200 | `flash_compensation` |
| 0xD201 | `dynamic_range_optimizer` |
| 0xD202 | `shooting_timing_pre_notification` |
| 0xD203 | `image_size` |
| 0xD206 | `license_download_status` |
| 0xD207 | `osd_image_mode` |
| 0xD208 | `camera_button_function_capability` |
| 0xD209 | `camera_button_function_multi_capability` |
| 0xD20A | `camera_dial_function_capability` |
| 0xD20C | `camera_button_function_status` |
| 0xD20D | `shutter_speed` |
| 0xD20E | `battery_level_indicator` |
| 0xD20F | `color_temperature` |
| 0xD210 | `biaxial_fine_tuning_g_m_direction` |
| 0xD211 | `aspect_ratio` |
| 0xD213 | `focus_indication` |
| 0xD214 | `predicted_maximum_file_size` |
| 0xD217 | `aelock_indication` |
| 0xD218 | `battery_remaining` |
| 0xD219 | `aps_c_setting` |
| 0xD21B | `picture_effect` |
| 0xD21C | `biaxial_fine_tuning_a_b_direction` |
| 0xD21D | `movie_recording_state` |
| 0xD21E | `iso_sensitivity` |
| 0xD21F | `felock_indication` |
| 0xD220 | `audio_signals_start_end` |
| 0xD221 | `liveview_status` |
| 0xD222 | `still_image_save_destination` |
| 0xD223 | `date_time_setting` |
| 0xD22C | `focus_area` |
| 0xD231 | `live_view_display_effect` |
| 0xD235 | `near_far_enable_status` |
| 0xD236 | `af_mf_hold_button_enable_status` |
| 0xD238 | `cancel_pixel_shift_shooting_button_enable_status` |
| 0xD239 | `pixel_shift_shooting_mode` |
| 0xD23A | `pixel_shift_shooting_number` |
| 0xD23B | `pixel_shift_shooting_interval` |
| 0xD23C | `pixel_shift_shooting_status` |
| 0xD23D | `progress_number_of_pixel_shift_shooting` |
| 0xD23F | `select_picture_profile` |
| 0xD241 | `file_format_movie` |
| 0xD242 | `recording_setting_movie` |
| 0xD248 | `media_slot1_status` |
| 0xD249 | `media_slot1_remaining_number_shots` |
| 0xD24A | `media_slot1_remaining_shooting_time` |
| 0xD24C | `focal_position` |
| 0xD24E | `awb_lock_indication` |
| 0xD24F | `interval_rec_mode` |
| 0xD250 | `interval_rec_status` |
| 0xD251 | `device_overheating_state` |
| 0xD252 | `jpeg_quality` |
| 0xD253 | `file_format_still` |
| 0xD254 | `focus_magnifier_setting` |
| 0xD255 | `af_tracking_sensitivity_still` |
| 0xD256 | `media_slot2_status` |
| 0xD257 | `media_slot2_remaining_number_shots` |
| 0xD258 | `media_slot2_remaining_shooting_time` |
| 0xD25A | `position_key_setting` |
| 0xD25B | `zoom_operation_enable_status` |
| 0xD25C | `zoom_scale` |
| 0xD25D | `zoom_bar_information` |
| 0xD25E | `zoom_speed_range` |
| 0xD25F | `zoom_setting` |
| 0xD260 | `zoom_type_status` |
| 0xD261 | `recording_time` |
| 0xD262 | `wireless_flash_setting` |
| 0xD263 | `red_eye_reduction` |
| 0xD264 | `remote_control_restriction_status` |
| 0xD267 | `liveview_area` |
| 0xD268 | `still_image_trans_size` |
| 0xD269 | `raw_j_pc_save_image` |
| 0xD26B | `custom_wb_capturable_area` |
| 0xD26C | `custom_wb_capture_frame_size` |
| 0xD26D | `custom_wb_capture_standby_operation` |
| 0xD26E | `custom_wb_capture_standby_cancel_operation` |
| 0xD26F | `custom_wb_capture_operation` |
| 0xD270 | `custom_wb_execution_state` |
| 0xD271 | `camera_setting_save_operation` |
| 0xD272 | `camera_setting_read_operation` |
| 0xD273 | `camera_setting_save_read_state` |
| 0xD274 | `ftp_setting_save_operation` |
| 0xD275 | `ftp_setting_read_operation` |
| 0xD276 | `ftp_setting_save_read_state` |
| 0xD279 | `media_slot1_format_enable_status` |
| 0xD27A | `media_slot2_format_enable_status` |
| 0xD27B | `media_format_progress_rate` |
| 0xD27C | `select_ftp_server` |
| 0xD27D | `media_slot1_ftp_transfer_status` |
| 0xD27E | `media_slot2_ftp_transfer_status` |
| 0xD27F | `ftp_connection_status` |
| 0xD280 | `ftp_connection_error_info` |
| 0xD281 | `high_resolution_ss_setting` |
| 0xD282 | `high_resolution_shutter_speed` |
| 0xD283 | `function_of_touch_operation` |
| 0xD284 | `remote_touch_operation_enable_status` |
| 0xD285 | `cancel_remote_touch_operation_enable_status` |
| 0xD286 | `recording_frame_rate_setting_movie` |
| 0xD287 | `compression_file_format_still` |
| 0xD288 | `raw_file_type` |
| 0xD289 | `media_slot1_raw_file_type` |
| 0xD28A | `media_slot2_raw_file_type` |
| 0xD28B | `media_slot1_file_format_still` |
| 0xD28C | `media_slot2_file_format_still` |
| 0xD28D | `media_slot1_jpeg_quality` |
| 0xD28E | `media_slot2_jpeg_quality` |
| 0xD28F | `media_slot1_image_size` |
| 0xD290 | `media_slot2_image_size` |
| 0xD291 | `transfer_compression_file` |
| 0xD292 | `media_slot1_quick_format_enable_state` |
| 0xD293 | `media_slot2_quick_format_enable_state` |
| 0xD294 | `cancel_media_format_enable_state` |
| 0xD295 | `contents_transfer_enable_status` |
| 0xD296 | `wifi_power_off_enable_status` |
| 0xD297 | `save_zoom_and_focus_position` |
| 0xD298 | `load_zoom_and_focus_position` |
| 0xD299 | `remocon_zoom_speed_type` |
| 0xD29A | `apsc_full_switching_setting` |
| 0xD29B | `apsc_full_switching_status` |
| 0xD29C | `movie_self_timer` |
| 0xD29D | `movie_self_timer_countdown_time` |
| 0xD29F | `movie_self_timer_repeat` |
| 0xD2A0 | `movie_self_timer_status` |
| 0xD2A1 | `focus_bracket_shot_num` |
| 0xD2A2 | `focus_bracket_focus_range` |
| 0xD2A3 | `step_zoom_mag_setting` |
| 0xD2A4 | `bulb_timer_setting` |
| 0xD2A5 | `bulb_exposure_time_setting` |
| 0xD2A6 | `elapsed_bulb_exposure_time` |
| 0xD2A7 | `remaining_bulb_exposure_time` |
| 0xD2A8 | `remaining_noise_reduction_time` |
| 0xD2B4 | `controlplayback_binary_version` |
| 0xD2B5 | `recording_file_number_movie` |
| 0xD2B6 | `ai_dictionary_upload_status` |
| 0xD2B9 | `short_video_length_setting` |
| 0xD2BA | `flicker_scan_status` |
| 0xD2BB | `flicker_scan_enable_status` |

### Actions « boutons » / déclenchement — 0xD2Cx–0xD2Fx (via ControlDevice)  (34 codes)

| Code | Nom symbolique |
|---|---|
| 0xD2C1 | `s1_button` |
| 0xD2C2 | `s2_button` |
| 0xD2C3 | `ael_button` |
| 0xD2C4 | `afl_button` |
| 0xD2C7 | `request_one_shooting` |
| 0xD2C8 | `movie_rec_button` |
| 0xD2C9 | `fel_button` |
| 0xD2D1 | `near_far` |
| 0xD2D2 | `af_mf_hold` |
| 0xD2D3 | `cancel_pixel_shift_shooting` |
| 0xD2D4 | `pixel_shift_shooting_mode` |
| 0xD2D7 | `focus_step_near` |
| 0xD2D8 | `focus_step_far` |
| 0xD2D9 | `awbl_button` |
| 0xD2DA | `program_shift` |
| 0xD2DB | `whiteBalance_initialize` |
| 0xD2DC | `af_area_position` |
| 0xD2DD | `zoom_operation` |
| 0xD2DF | `custom_wb_capture_standby` |
| 0xD2E0 | `custom_wb_capture_standby_cancel` |
| 0xD2E1 | `custom_wb_capture` |
| 0xD2E2 | `selected_media_format` |
| 0xD2E3 | `high_resolution_ss_adjust` |
| 0xD2E4 | `remote_touch_operation` |
| 0xD2E5 | `cancel_remote_touch_operation` |
| 0xD2E6 | `s1_and_s2_button` |
| 0xD2E7 | `cancel_media_format` |
| 0xD2E8 | `wifi_power_off` |
| 0xD2E9 | `save_zoom_and_focus_position` |
| 0xD2EA | `load_zoom_and_focus_position` |
| 0xD2EB | `apsc_full_switching` |
| 0xD2F0 | `high_resolution_ss_adjust_integral_multiples` |
| 0xD2F1 | `flicker_scan` |
| 0xD2F3 | `rec_settings_reset` |

### Codes de contrôle système — 0xD3xx (via ControlDevice)  (19 codes)

| Code | Nom symbolique |
|---|---|
| 0xD300 | `pixel_mapping` |
| 0xD301 | `power_off` |
| 0xD302 | `time_code_preset_reset` |
| 0xD303 | `user_bit_preset_reset` |
| 0xD304 | `sensor_cleaning` |
| 0xD305 | `reset_picture_profile` |
| 0xD306 | `reset_creative_look` |
| 0xD308 | `wifi_direct_mode_off` |
| 0xD309 | `camera_button_function` |
| 0xD30A | `camera_button_function_multi` |
| 0xD30B | `camera_dial_function` |
| 0xD30D | `tracking_on_af_on_button` |
| 0xD30E | `forced_file_number_reset` |
| 0xD30F | `set_select_on_camera_transfer_enable` |
| 0xD310 | `set_select_on_camera_transfer_mode` |
| 0xD311 | `cancel_select_on_camera_transfer` |
| 0xD312 | `set_post_view_enable` |
| 0xD313 | `set_live_view_enable` |
| 0xD314 | `create_new_folder_still` |
