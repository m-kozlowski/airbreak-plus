#ifndef AS11_STUBS_H
#define AS11_STUBS_H

extern int DataItem_get_var_id_virtual(void *item);
extern int DataItem_read_value_by_id(unsigned short var_id);
extern void DataItem_write_raw_by_id(unsigned short var_id, int raw_value);
extern void AsvFeature_update(void *ctx);
extern void FeedbackInput_get_ref(int **value, unsigned int slot);
extern void FeedbackOutput_get_ref(float **value, unsigned int slot);

#endif
