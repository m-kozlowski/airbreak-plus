#ifndef AS11_STUBS_H
#define AS11_STUBS_H

extern int DataItem_get_var_id_virtual(void *item);
extern int DataItem_read_bytes_by_id(unsigned short var_id, void *buffer, unsigned int buffer_size);
extern int DataItem_read_value_by_id(unsigned short var_id);
extern void DataItem_set_visible_by_id(unsigned short var_id, int visible);
extern void DataItem_write_raw_by_id(unsigned short var_id, int raw_value);
extern void DataItem_write_text_notify_by_id(unsigned short var_id, const char *text);
extern void *memset(void *dest, int value, unsigned int length);
extern void AsvFeature_update(void *ctx);
extern void FeedbackInput_get_ref(int **value, unsigned int slot);
extern void FeedbackOutput_get_ref(float **value, unsigned int slot);
extern void *heap_alloc(unsigned int size);

/* Native OXI client methods; callback-interface adjustors use self + 8. */
extern void ble_oxi_gatt_client_on_stack_event(void *client, const unsigned int *event);
extern unsigned char ble_stack_event_connection_id(const unsigned int *event);
extern void ble_oxi_gatt_client_queue_connect(void *client, unsigned int address_lo,
    unsigned int address_hi, unsigned char address_type, unsigned int context);
extern void ble_oxi_gatt_client_request_disconnect(void *client);
extern void ble_oxi_gatt_client_reset_connection_state(void *client);
extern void callback_notifier_invoke(void *callback, unsigned int event);

/* Native registry and encoder entry points used by Airbreak RPC providers. */
extern void rpc_profile_json_formatter_registry_ctor(void);
extern void *rpc_profile_json_formatter_registration_ctor(void *registration);
extern int json_encoder_write_raw_span(
    void *formatter, void *encoder, const void *span);

/* Native cellular FileFetcher and flow-generator upgrade state machine. */
extern int gfile_fetcher_control_can_start(void *control);
extern void upgrade_command_executor_set_result(void *executor, unsigned int result);
extern void upgrade_command_executor_reset(void *executor);
extern void upgrade_command_executor_notify_result(void *executor, unsigned int result);
extern void upgrade_command_executor_set_state_after_hook(void);
extern void GuiTextValueFormatter_ctor(void *formatter);
extern void GuiTextValueFormatter_dtor(void *formatter);
extern void *GuiMenuTextValueListItem_ctor(
    void *item, unsigned int var_id, unsigned int label_id, void *formatter);
extern void *gui_menu_data_value_callback_ctor_empty(void *callback);
extern void gui_menu_data_value_callback_dtor(void *callback);
extern void *GuiMenuDataValueListItem_ctor(
    void *item, unsigned int var_id, unsigned int label_id,
    unsigned int title_id, unsigned int activity_id, void *controller,
    void *callback, unsigned int flags);
extern void *GuiScroller_ctor(
    void *scroller,
    unsigned int arg2,
    unsigned int arg3,
    unsigned int arg4,
    unsigned int arg5,
    void **items,
    unsigned int item_count,
    unsigned int arg8,
    unsigned int arg9,
    unsigned int arg10,
    unsigned int arg11,
    unsigned int arg12);
extern void GuiPaint_DrawLocalizedTextById(
    unsigned int text_id,
    void *rect,
    unsigned int text_size,
    unsigned int font,
    int clip,
    unsigned int alignment);
extern void GuiPaint_DrawStringInRect(
    const char *text,
    void *rect,
    unsigned int text_size,
    unsigned int font,
    int clip,
    unsigned int alignment,
    int font_slot);
extern int gui_localized_text_font_slot_for_id(unsigned int text_id);
extern unsigned int datetime_current_local_milliseconds_of_day(void);
extern void *user_interface_root_widget_ctor(
    void *root,
    unsigned int arg2,
    unsigned int arg3,
    unsigned int arg4);
extern void user_interface_root_widget_status_blink_timer_callback_adjustor(
    void *callback_self);
extern void thunk_gui_timer_handle_reschedule_with_optional_delay(
    void *timer,
    unsigned int delay_ms);
extern void gui_owned_object_invalidate(void *object);

/* Geometry accessors return global coordinates; paint calls use widget-local ones. */
extern void GuiTreatmentScreenSinglePressure_paint(void *screen);
extern void GuiTreatmentScreen_timer_callback(void *screen, void *timer);
extern void GuiTreatmentScreen_clear_background(void *screen);
extern void GuiScroller_paint(void *scroller);
extern void GuiTreatmentDots_paint(void *dots);
extern void *gui_widget_parent(void *widget);
extern unsigned int gui_window_parent_handle(unsigned int window);
extern int gui_widget_is_visible(void *widget);
extern int gui_widget_width(void *widget);
extern int gui_widget_height(void *widget);
extern int gui_widget_x(void *widget);
extern int gui_widget_y(void *widget);
extern void gui_widget_invalidate_rect(void *widget, int x0, int y0, int x1, int y1);
extern unsigned int gui_time_milliseconds(void);
extern void stopwatch_reset(void *stopwatch, unsigned int elapsed);

/* Native 112-byte drawing context; clip bounds are inclusive screen coordinates. */
typedef struct {
    unsigned char prefix[8];
    short clip_left, clip_top, clip_right, clip_bottom;
    unsigned char state[0x3c];
    int origin_x, origin_y;
    unsigned char tail[0x1c];
} gui_render_context_t;
extern void gui_render_context_snapshot(gui_render_context_t *context);
extern void user_interface_update_gui_state_and_cache(void *context);

/* Native therapy widgets. Constructors retain child arrays and scroll states. */
extern void *GuiTherapyListItem_ctor(void *item, unsigned int height);
extern void *GuiTherapySummaryRow_ctor(void *item, unsigned int height, unsigned int first, unsigned int second, unsigned int label);
extern void *GuiTherapyValueRow_ctor(void *item, unsigned int var_id, unsigned int label, unsigned int unit, int scale);
extern void *GuiTherapyPairRow_ctor(void *item, unsigned int first, unsigned int second,
    unsigned int label, unsigned int title, unsigned int activity, unsigned int empty,
    unsigned int unit, int scale, int index, void *controller);
extern void *GuiTherapyDoubleNodeAdapter_ctor(void *adapter, unsigned int first, unsigned int index, unsigned int second);
extern void *GuiTherapyAdapterRow_ctor(void *item, void *adapter, unsigned int label, unsigned int unit);
extern void *GuiTherapyRowGroup_ctor(void *group, void **items, unsigned int count, unsigned int visible_rows);
extern void *GuiTherapyScrollbar_ctor(void *bar, unsigned int width, unsigned int gap, unsigned int inset, unsigned int padding);
extern void GuiScrollState_ctor(void *state);
extern void *GuiTreatmentScreen_ctor(void *screen, void *parent, void *root, unsigned int label,
    void *scroller, unsigned int context, unsigned int period);
extern void GuiScroller_update_items(void *scroller);
extern void GuiPageAction_ctor(void *action, const unsigned char *page);
extern void GuiSwitchAction_add(void *action, unsigned int value, void *target);
extern void *GuiDataItemSwitch_ctor(void *action, unsigned int var_id, void *fallback);
extern int GuiMenuCentre_is_therapy_page(const unsigned char *page);

typedef struct {
    unsigned int count;
    unsigned char transparent;
    unsigned char reserved[3];
    const unsigned int *colors;
} gui_palette_t;

typedef struct {
    unsigned short width, height, stride, bits_per_pixel;
    const unsigned char *pixels;
    const gui_palette_t *palette;
    const void *methods;
} gui_bitmap_t;

/* A null methods pointer selects packed pixels with native origin/clipping. */
extern void gui_paint_draw_bitmap(const gui_bitmap_t *bitmap, int x, int y);

/* Native touch and backlight entry points used by the keep-awake gesture. */
extern void touch_screen_controller_process_report(void *controller);
extern void touch_screen_controller_discard_all_reports(void *controller);
extern unsigned int ring_buffer_free_count(void *ring);
extern void *ring_buffer_front_ptr(void *ring);
extern void ring_buffer_write_elements(
    void *ring, const void *elements, unsigned int count);
extern void user_interface_process_touch_events(void *user_interface);
extern void *led_status_controller_singleton(void);
extern unsigned int led_channel_select_target_intensity(void *channel);
extern unsigned int ambient_light_mode_is_dark(void);
extern void *led_timeout_channel_slot_by_index(
    void *channels, unsigned int index);
extern void led_channel_schedule_transition(
    void *channel,
    unsigned int priority,
    unsigned int target,
    unsigned int duration_ms,
    unsigned int arg5,
    unsigned int arg6);
extern void led_timeout_fade_channels_off(void *timeout);

#endif
