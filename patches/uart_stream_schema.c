/*
 * Extend G C with Airbreak metadata.
 *
 * Live-stream field layouts:
 *
 *   G C &TAG = NN VAR:WW ...
 *
 * NN is the field count and WW is the field width in hexadecimal characters.
 * Both values are encoded as two hexadecimal digits.
 *
 * Custom settings are exposed through the final menu registry:
 *
 *   G C &CSG       = VV NN
 *   G C &CSG INDEX = ENTRY
 *
 * VV is the extension version and NN is the registry entry count. INDEX is a
 * two-digit hexadecimal record index. The stock G C handler still handles
 * every request outside these extensions.
 */

typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;

#include "custom_menu_registry.h"

typedef struct {
    u8 field_count;
    char name[3];
    u32 config_a;
    const u16 *var_ids;
    u32 config_b;
    u32 config_c;
} g26_record_t;

typedef struct {
    u8 field_count;
    char name[3];
    u32 config_a;
    const u16 *var_ids;
    u32 config_b;
} g27_record_t;

typedef int (*gc_handler_t)(void *self, const char *request, int var_id,
                            char *response, unsigned int response_size);

extern void **ccx_get_globals(void);
extern void variable_lookup_handler(void *handler, int var_id, int flags);
extern void variable_handler_release(void *handler);
extern void variable_handler_get_uart_name(void *handler, char *name);
extern unsigned int variable_handler_wire_width(void *handler);
extern const char *string_id_lookup_current_locale(const u16 *str_id);
extern unsigned int parse_hex_u16(const char *text, int max_length,
                                  int stop_at_space);
extern int snprintf(char *buffer, unsigned int size, const char *format, ...);
extern const u32 uart_stream_schema_original_handler;
extern const u32 uart_custom_settings_registry_addr;

enum {
    G26_RECORD_COUNT = 8,
    G27_RECORD_COUNT = 3,
    VARIABLE_HANDLER_WORDS = 16,
    DESCRIPTOR_NAME_STR_OFFSET = 0x06,
    G4_DECIMALS_OFFSET = 0x14,
    G4_SCALE_OFFSET = 0x16,
    G4_STEP_OFFSET = 0x18,
    G4_UNITS_STR_OFFSET = 0x1a,
    CUSTOM_SETTINGS_PROTOCOL_VERSION = 1,
};

static int same_name(const char *left, const char *right)
{
    return left[0] == right[0] && left[1] == right[1] && left[2] == right[2];
}

static const u16 *find_stream(const char *name, u8 *field_count)
{
    void **globals = ccx_get_globals();
    const g26_record_t *g26 = (const g26_record_t *)globals[26];
    const g27_record_t *g27 = (const g27_record_t *)globals[27];
    unsigned int i;

    for (i = 0; i < G26_RECORD_COUNT; ++i) {
        if (same_name(name, g26[i].name)) {
            *field_count = g26[i].field_count;
            return g26[i].var_ids;
        }
    }
    for (i = 0; i < G27_RECORD_COUNT; ++i) {
        if (same_name(name, g27[i].name)) {
            *field_count = g27[i].field_count;
            return g27[i].var_ids;
        }
    }
    return 0;
}

static char hex_digit(unsigned int value)
{
    value &= 0xf;
    return (value < 10) ? (char)('0' + value) : (char)('A' + value - 10);
}

static int append_char(char **cursor, char *end, char value)
{
    if (*cursor + 1 >= end)
        return 0;
    *(*cursor)++ = value;
    return 1;
}

static int append_hex_byte(char **cursor, char *end, unsigned int value)
{
    return append_char(cursor, end, hex_digit(value >> 4)) &&
           append_char(cursor, end, hex_digit(value));
}

static unsigned int text_length(const char *text)
{
    unsigned int length = 0;

    while (text[length] != '\0' && length < 0xff)
        length++;
    return length;
}

static const char *localized_string(u16 str_id)
{
    const char *text = string_id_lookup_current_locale(&str_id);
    return text ? text : "";
}

static int write_error(char *response, unsigned int response_size,
                       const char error[4])
{
    unsigned int i;

    if (response_size == 0)
        return 0;
    for (i = 0; i < 4 && i + 1 < response_size; ++i)
        response[i] = error[i];
    response[i] = '\0';
    return 0;
}

static int formatted_response(char *response, unsigned int response_size,
                              int length)
{
    if (length < 0 || (unsigned int)length >= response_size)
        return write_error(response, response_size, "6052");
    return 1;
}

static int write_schema(const u16 *var_ids, u8 field_count, char *response,
                        unsigned int response_size)
{
    char *cursor = response;
    char *end = response + response_size;
    unsigned int i;

    if (!append_hex_byte(&cursor, end, field_count))
        return write_error(response, response_size, "6052");

    for (i = 0; i < field_count; ++i) {
        u32 handler[VARIABLE_HANDLER_WORDS];
        char name[4] = {0, 0, 0, 0};
        unsigned int width;

        variable_lookup_handler(handler, var_ids[i], 0);
        variable_handler_get_uart_name(handler, name);
        width = variable_handler_wire_width(handler);
        variable_handler_release(handler);

        if (width > 0xff ||
            !append_char(&cursor, end, ' ') ||
            !append_char(&cursor, end, name[0]) ||
            !append_char(&cursor, end, name[1]) ||
            !append_char(&cursor, end, name[2]) ||
            !append_char(&cursor, end, ':') ||
            !append_hex_byte(&cursor, end, width))
            return write_error(response, response_size, "6052");
    }

    *cursor = '\0';
    return 1;
}

static const custom_menu_entry_t *custom_settings_registry(void)
{
    const custom_menu_entry_t *registry =
        (const custom_menu_entry_t *)uart_custom_settings_registry_addr;

    if (!registry || (u32)registry == 0xffffffffu)
        return 0;
    return registry;
}

static int custom_menu_entry_is_end(const custom_menu_entry_t *entry)
{
    return entry->container == 0xff || entry->item_id == 0xffff;
}

static unsigned int custom_settings_entry_count(void)
{
    const custom_menu_entry_t *entry = custom_settings_registry();
    unsigned int count = 0;

    while (entry && count < CUSTOM_MENU_REGISTRY_LIMIT &&
           !custom_menu_entry_is_end(entry)) {
        count++;
        entry++;
    }
    return count;
}

static int write_custom_settings_header(char *response,
                                        unsigned int response_size)
{
    int length;

    length = snprintf(response, response_size, "%02X %02X",
                      CUSTOM_SETTINGS_PROTOCOL_VERSION,
                      custom_settings_entry_count());
    return formatted_response(response, response_size, length);
}

static int write_custom_settings_entry(unsigned int index, char *response,
                                       unsigned int response_size)
{
    const custom_menu_entry_t *registry = custom_settings_registry();
    unsigned int count = custom_settings_entry_count();
    const custom_menu_entry_t *entry;
    u32 handler[VARIABLE_HANDLER_WORDS];
    const u8 *descriptor = 0;
    char name[4] = {0, 0, 0, 0};
    const char *units;
    int length;

    if (!registry || index >= count)
        return write_error(response, response_size, "6033");
    entry = registry + index;

    if (entry->flags & (CUSTOM_MENU_FLAG_PAGE | CUSTOM_MENU_FLAG_HEADING)) {
        length = snprintf(response, response_size, "%c %02X %s",
                          (entry->flags & CUSTOM_MENU_FLAG_PAGE) ? 'P' : 'H',
                          entry->container, localized_string(entry->item_id));
        return formatted_response(response, response_size, length);
    }

    variable_lookup_handler(handler, entry->item_id, 0);
    descriptor = (const u8 *)handler[3];
    variable_handler_get_uart_name(handler, name);
    if (entry->flags & CUSTOM_MENU_FLAG_G4_NUMERIC) {
        units = localized_string(*(const u16 *)(descriptor +
                                                G4_UNITS_STR_OFFSET));
        length = snprintf(
            response, response_size,
            "V4 %02X %08X %s %04X %04X %02X %02X:%s %s",
            entry->container, entry->mode_mask, name,
            *(const u16 *)(descriptor + G4_SCALE_OFFSET),
            *(const u16 *)(descriptor + G4_STEP_OFFSET),
            descriptor[G4_DECIMALS_OFFSET], text_length(units), units,
            localized_string(*(const u16 *)(descriptor +
                                             DESCRIPTOR_NAME_STR_OFFSET)));
    } else {
        length = snprintf(
            response, response_size, "V8 %02X %08X %s %s",
            entry->container, entry->mode_mask, name,
            localized_string(*(const u16 *)(descriptor +
                                             DESCRIPTOR_NAME_STR_OFFSET)));
    }
    variable_handler_release(handler);
    return formatted_response(response, response_size, length);
}

static int handle_custom_settings(const char *request, char *response,
                                  unsigned int response_size)
{
    unsigned int index;

    if (request[8] == '\0')
        return write_custom_settings_header(response, response_size);
    if (request[8] != ' ' || request[9] == '\0' || request[10] == '\0' ||
        request[11] != '\0')
        return write_error(response, response_size, "600E");
    index = parse_hex_u16(request + 9, 2, 0);
    if (index == 0xffffffffu)
        return write_error(response, response_size, "6031");
    return write_custom_settings_entry(index, response, response_size);
}

int start(void *self, const char *request, int var_id, char *response,
          unsigned int response_size)
{
    gc_handler_t original = (gc_handler_t)uart_stream_schema_original_handler;
    const u16 *var_ids;
    u8 field_count;

    if (request[4] == '&' && same_name(request + 5, "CSG"))
        return handle_custom_settings(request, response, response_size);

    if (request[4] == '&' && request[8] == '\0') {
        var_ids = find_stream(request + 5, &field_count);
        if (var_ids)
            return write_schema(var_ids, field_count, response, response_size);
    }

    return original(self, request, var_id, response, response_size);
}
