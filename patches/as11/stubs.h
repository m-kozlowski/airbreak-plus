#ifndef AS11_STUBS_H
#define AS11_STUBS_H

extern int DataItem_get_var_id_virtual(void *item);
extern int DataItem_read_value_by_id(unsigned short var_id);
extern void DataItem_set_visible_by_id(unsigned short var_id, int visible);
extern void DataItem_write_raw_by_id(unsigned short var_id, int raw_value);
extern void AsvFeature_update(void *ctx);
extern void FeedbackInput_get_ref(int **value, unsigned int slot);
extern void FeedbackOutput_get_ref(float **value, unsigned int slot);
extern void *heap_alloc(unsigned int size);
extern void GuiTextValueFormatter_ctor(void *formatter);
extern void GuiTextValueFormatter_dtor(void *formatter);
extern void *GuiMenuTextValueListItem_ctor(
    void *item, unsigned int var_id, unsigned int label_id, void *formatter);
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

#endif
