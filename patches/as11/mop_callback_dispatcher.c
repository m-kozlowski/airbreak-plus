/*
 * Owns the shared EnumDataItem writeback vtable slot. The stock writeback is
 * always called; registered feature handlers run only for MOP.
 */

#include "stubs.h"
#include "vars.h"

volatile const unsigned int mop_callback_handler_table[6]
    __attribute__((used, section(".rodata.params"))) = {
        0xFFFFFFFFu,
        0xFFFFFFFFu,
        0xFFFFFFFFu,
        0xFFFFFFFFu,
        0xFFFFFFFFu,
        0xFFFFFFFFu,
    };

void __attribute__((section(".text.0.main")))
start(void *item)
{
    unsigned int stock_writeback = mop_callback_handler_table[0];
    ((void (*)(void *))stock_writeback)(item);

    if ((unsigned int)DataItem_get_var_id_virtual(item) != VAR_ID_MOP)
        return;

    for (unsigned int index = 1; index < 6; ++index) {
        unsigned int handler = mop_callback_handler_table[index];
        if (handler == 0 || handler == 0xFFFFFFFFu)
            break;
        ((void (*)(void))handler)();
    }
}
