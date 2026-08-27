/*
 * Extend G C with live-stream field layouts:
 *
 *   G C &TAG = NN VAR:WW ...
 *
 * NN is the field count and WW is the field width in hexadecimal characters.
 * Both values are encoded as two hexadecimal digits. The stock G C handler
 * still handles every request outside the globals[26]/globals[27] channels.
 */

typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;

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
extern const u32 uart_stream_schema_original_handler;

enum {
    G26_RECORD_COUNT = 8,
    G27_RECORD_COUNT = 3,
    VARIABLE_HANDLER_WORDS = 16,
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

int start(void *self, const char *request, int var_id, char *response,
          unsigned int response_size)
{
    gc_handler_t original = (gc_handler_t)uart_stream_schema_original_handler;
    const u16 *var_ids;
    u8 field_count;

    if (request[4] == '&' && request[8] == '\0') {
        var_ids = find_stream(request + 5, &field_count);
        if (var_ids)
            return write_schema(var_ids, field_count, response, response_size);
    }

    return original(self, request, var_id, response, response_size);
}
