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

#endif
