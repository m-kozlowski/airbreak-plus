/* Download an HTTP resource through the native cellular FileFetcher. */

#include "stubs.h"
#include "rpc_object.h"

#define URL_HOST_CAPACITY 128u
#define URL_PATH_CAPACITY 512u
#define URL_CAPACITY (URL_HOST_CAPACITY + URL_PATH_CAPACITY)
#define MAX_UPGRADE_PAYLOAD_SIZE 2252800u

enum download_state {
    DOWNLOAD_IDLE,
    DOWNLOAD_QUEUED,
    DOWNLOAD_ACTIVE,
    DOWNLOAD_COMPLETE,
    DOWNLOAD_ERROR,
    DOWNLOAD_EXTERNAL,
    DOWNLOAD_UNAVAILABLE,
};

typedef int (*config_get_int_t)(void *self, const char *key);
typedef int (*config_equals_t)(void *self, const char *key, const char *value);
typedef void (*config_set_t)(void *self, const char *key, const char *value);

typedef struct {
    const void **vtable;
} native_object_t;

typedef struct {
    const void *vtable;
    void *config;
} gfile_fetcher_control_t;

typedef struct {
    unsigned char reserved[0x1Cu];
    gfile_fetcher_control_t *control;
} gfile_fetcher_task_t;

typedef struct {
    unsigned char reserved[0x0Cu];
    void *config;
} upgrade_command_executor_t;

typedef struct {
    char url[URL_CAPACITY];
    unsigned int host_end;
    unsigned int path_start;
    unsigned int port;
} download_request_t;

/* The patcher supplies the RAM slot holding the native FileFetcher task. */
volatile const unsigned int cellular_download_task_pointer_slot
    __attribute__((used, section(".rodata.params"))) = 0xFFFFFFFFu;

static const char key_path[] = "UPGRD_PATH";
static const char key_host[] = "UPGRD_HOST";
static const char key_port[] = "UPGRD_PORT";
static const char key_protocol[] = "UPGRD_HTTPS";
static const char key_type[] = "UPGRD_TYPE";
static const char key_size[] = "UPGRD_SIZE";
static const char key_hash[] = "UPGRD_HASH";
static const char key_status[] = "UPGRD_STATUS_URI";
static const char key_bytes_stored[] = "UPGRD_BYTES_STORED";
static const char key_start_time[] = "UPGRD_START_TIME";
static const char key_state[] = "UPGRD_STATE";

static const char marker_queued[] = "airbreak:queued";
static const char marker_active[] = "airbreak:active";
static const char marker_complete[] = "airbreak:complete";
static const char marker_error[] = "airbreak:error";

static void config_set(void *config, const char *key, const char *value)
{
    const void **vtable = ((native_object_t *)config)->vtable;
    ((config_set_t)vtable[2])(config, key, value);
}

static int config_get_int(void *config, const char *key)
{
    const void **vtable = ((native_object_t *)config)->vtable;
    return ((config_get_int_t)vtable[4])(config, key);
}

static int config_equals(void *config, const char *key, const char *value)
{
    const void **vtable = ((native_object_t *)config)->vtable;
    return ((config_equals_t)vtable[7])(config, key, value);
}

static gfile_fetcher_control_t *download_control(void *context)
{
    unsigned int slot = *(const volatile unsigned int *)context;
    gfile_fetcher_task_t *task;

    if (slot == 0u || slot == 0xFFFFFFFFu)
        return 0;
    task = *(gfile_fetcher_task_t **)slot;
    return task == 0 ? 0 : task->control;
}

static enum download_state current_state(void *config)
{
    /* CamlData survives task restarts and carries the provider's local state. */
    if (config_equals(config, key_status, marker_queued))
        return DOWNLOAD_QUEUED;
    if (config_equals(config, key_status, marker_active))
        return DOWNLOAD_ACTIVE;
    if (config_equals(config, key_status, marker_complete))
        return DOWNLOAD_COMPLETE;
    if (config_equals(config, key_status, marker_error))
        return DOWNLOAD_ERROR;
    if (!config_equals(config, key_path, ""))
        return DOWNLOAD_EXTERNAL;
    return DOWNLOAD_IDLE;
}

static const char *state_name(enum download_state state)
{
    static const char idle[] = "idle";
    static const char queued[] = "queued";
    static const char active[] = "downloading";
    static const char complete[] = "complete";
    static const char error[] = "error";
    static const char external[] = "external";
    static const char unavailable[] = "unavailable";

    switch (state) {
    case DOWNLOAD_QUEUED: return queued;
    case DOWNLOAD_ACTIVE: return active;
    case DOWNLOAD_COMPLETE: return complete;
    case DOWNLOAD_ERROR: return error;
    case DOWNLOAD_EXTERNAL: return external;
    case DOWNLOAD_UNAVAILABLE: return unavailable;
    default: return idle;
    }
}

static const unsigned char *skip_space(
    const unsigned char *cursor, const unsigned char *end)
{
    while (cursor != end &&
           (*cursor == ' ' || *cursor == '\t' ||
            *cursor == '\r' || *cursor == '\n'))
        ++cursor;
    return cursor;
}

static int parse_string(
    const unsigned char **cursor,
    const unsigned char *end,
    char *output,
    unsigned int capacity)
{
    const unsigned char *input = *cursor;
    unsigned int length = 0;

    if (input == end || *input++ != '"')
        return 0;
    while (input != end && *input != '"') {
        unsigned char value = *input++;
        if (value == '\\') {
            if (input == end)
                return 0;
            value = *input++;
            if (value != '"' && value != '\\' && value != '/')
                return 0;
        }
        if (value < 0x20 || length + 1u >= capacity)
            return 0;
        output[length++] = (char)value;
    }
    if (input == end || *input++ != '"')
        return 0;
    output[length] = '\0';
    *cursor = input;
    return 1;
}

static int strings_equal(const char *left, const char *right)
{
    while (*left != '\0' && *left == *right) {
        ++left;
        ++right;
    }
    return *left == *right;
}

static int parse_http_url(download_request_t *request)
{
    static const char prefix[] = "http://";
    const char *url = request->url;
    const char *cursor = url;
    unsigned int prefix_index;
    unsigned int host_length = 0;
    unsigned int path_length = 0;
    unsigned int port = 0;

    for (prefix_index = 0; prefix[prefix_index] != '\0'; ++prefix_index) {
        if (*cursor++ != prefix[prefix_index])
            return 0;
    }
    while (*cursor != '\0' && *cursor != ':' && *cursor != '/') {
        if (*cursor == '@' || host_length + 1u >= URL_HOST_CAPACITY)
            return 0;
        ++host_length;
        ++cursor;
    }
    if (host_length == 0)
        return 0;
    request->host_end = (unsigned int)(cursor - url);

    request->port = 80u;
    if (*cursor == ':') {
        ++cursor;
        if (*cursor < '0' || *cursor > '9')
            return 0;
        while (*cursor >= '0' && *cursor <= '9') {
            unsigned int digit = (unsigned int)(*cursor++ - '0');
            if (port > (65535u - digit) / 10u)
                return 0;
            port = port * 10u + digit;
        }
        if (port == 0u)
            return 0;
        request->port = port;
    }

    if (*cursor != '/')
        return 0;
    request->path_start = (unsigned int)(cursor - url);
    while (*cursor != '\0') {
        if (path_length + 1u >= URL_PATH_CAPACITY)
            return 0;
        ++path_length;
        ++cursor;
    }
    return 1;
}

static int parse_request(
    const rpc_json_span_t *value, download_request_t *request)
{
    const unsigned char *cursor = skip_space(value->begin, value->end);
    char key[8];
    unsigned int have_url = 0;

    if (cursor == value->end || *cursor++ != '{')
        return 0;
    for (;;) {
        cursor = skip_space(cursor, value->end);
        if (cursor != value->end && *cursor == '}') {
            ++cursor;
            break;
        }
        if (!parse_string(&cursor, value->end, key, sizeof(key)))
            return 0;
        cursor = skip_space(cursor, value->end);
        if (cursor == value->end || *cursor++ != ':')
            return 0;
        cursor = skip_space(cursor, value->end);

        if (strings_equal(key, "url") && !have_url) {
            if (!parse_string(&cursor, value->end, request->url,
                    sizeof(request->url)) || !parse_http_url(request))
                return 0;
            have_url = 1;
        } else {
            return 0;
        }

        cursor = skip_space(cursor, value->end);
        if (cursor != value->end && *cursor == ',') {
            ++cursor;
            continue;
        }
        if (cursor != value->end && *cursor == '}') {
            ++cursor;
            break;
        }
        return 0;
    }
    cursor = skip_space(cursor, value->end);
    return cursor == value->end && have_url;
}

static char *append_text(char *output, const char *text)
{
    while (*text != '\0')
        *output++ = *text++;
    return output;
}

static char *append_uint(char *output, unsigned int value)
{
    char digits[10];
    unsigned int count = 0;

    do {
        digits[count++] = (char)('0' + value % 10u);
        value /= 10u;
    } while (value != 0u);
    while (count != 0u)
        *output++ = digits[--count];
    return output;
}

static void uint_to_text(char output[11], unsigned int value)
{
    char *end = append_uint(output, value);
    *end = '\0';
}

static int cellular_download_write_value(void *context, void *encoder)
{
    gfile_fetcher_control_t *control = download_control(context);
    enum download_state state = DOWNLOAD_UNAVAILABLE;
    unsigned int bytes_stored = 0;
    unsigned int size = 0;
    char json[112];
    char *end = json;
    rpc_json_span_t span;

    if (control != 0) {
        state = current_state(control->config);
        bytes_stored = (unsigned int)config_get_int(
            control->config, key_bytes_stored);
        if (state == DOWNLOAD_COMPLETE || state == DOWNLOAD_EXTERNAL)
            size = (unsigned int)config_get_int(control->config, key_size);
    }

    end = append_text(end, "{\"state\":\"");
    end = append_text(end, state_name(state));
    end = append_text(end, "\",\"bytesStored\":");
    end = append_uint(end, bytes_stored);
    end = append_text(end, ",\"size\":");
    end = append_uint(end, size);
    *end++ = '}';

    span.begin = (const unsigned char *)json;
    span.end = (const unsigned char *)end;
    return json_encoder_write_raw_span(context, encoder, &span);
}

static int cellular_download_write_schema(void *context, void *encoder)
{
    static const unsigned char schema[] =
        "{\"type\":\"object\",\"required\":[\"url\"],"
        "\"properties\":{\"url\":{\"type\":\"string\"}}}";
    const rpc_json_span_t span = {
        schema,
        schema + sizeof(schema) - 1u,
    };

    return json_encoder_write_raw_span(context, encoder, &span);
}

static int cellular_download_apply_value(
    void *context, const rpc_json_span_t *value)
{
    gfile_fetcher_control_t *control = download_control(context);
    download_request_t request;
    char port[11];
    char size[11];
    char host_separator;

    if (control == 0 || !config_equals(control->config, key_path, "") ||
            !parse_request(value, &request))
        return 0;

    uint_to_text(port, request.port);
    uint_to_text(size, MAX_UPGRADE_PAYLOAD_SIZE);

    /* Queue only after every native FileFetcher input has been committed. */
    config_set(control->config, key_path, request.url + request.path_start);
    host_separator = request.url[request.host_end];
    request.url[request.host_end] = '\0';
    config_set(control->config, key_host, request.url + 7u);
    request.url[request.host_end] = host_separator;
    config_set(control->config, key_port, port);
    config_set(control->config, key_protocol, "http");
    config_set(control->config, key_type, "FG");
    /* Native storage always reserves its fixed 2252804-byte Upgrade.abc.
     * This accepted maximum lets HTTP determine the actual response length.
     */
    config_set(control->config, key_size, size);
    config_set(control->config, key_hash, "");
    config_set(control->config, key_bytes_stored, "0");
    config_set(control->config, key_start_time, "");
    config_set(control->config, key_state, "");
    config_set(control->config, key_status, marker_queued);
    return 1;
}

static const char cellular_download_name[] = "AirbreakDownload";

const rpc_object_t cellular_download_rpc_object
    __attribute__((used, section(".rodata.rpc_object"))) = {
        .name = cellular_download_name,
        .name_length = sizeof(cellular_download_name) - 1u,
        .dataitem_var_id = RPC_OBJECT_NO_DATAITEM,
        .context = (void *)&cellular_download_task_pointer_slot,
        .write_value = cellular_download_write_value,
        .write_schema = cellular_download_write_schema,
        .apply_value = cellular_download_apply_value,
    };

/* Local requests use the FileFetcher transport without cloud registration. */
int cellular_download_can_start(gfile_fetcher_control_t *control)
{
    enum download_state state = current_state(control->config);

    if (state != DOWNLOAD_QUEUED && state != DOWNLOAD_ACTIVE)
        return gfile_fetcher_control_can_start(control);

    config_set(control->config, key_status, marker_active);
    return 1;
}

static void finish_local_request(void *config)
{
    config_set(config, key_path, "");
    config_set(config, key_host, "");
    config_set(config, key_port, "");
    config_set(config, key_protocol, "");
    config_set(config, key_type, "");
    config_set(config, key_hash, "");
}

/* Continue in the stock function immediately after its replaced prologue. */
static void __attribute__((naked)) stock_set_state(
    void *executor, unsigned int state)
{
    __asm volatile(
        "push {r0,r1,r4,r5,r6,lr}\n"
        "mov r4,r0\n"
        "b upgrade_command_executor_set_state_after_hook\n"
    );
}

void cellular_download_set_state(void *executor, unsigned int state)
{
    void *config = ((upgrade_command_executor_t *)executor)->config;
    enum download_state local_state = current_state(config);
    char size[11];

    if (local_state >= DOWNLOAD_QUEUED && local_state <= DOWNLOAD_ERROR) {
        /* Replace CheckFile or Error with a local Done transition. Result 5
         * completes Done without posting to a cloud status URI.
         */
        if (state == 3u) {
            uint_to_text(size, (unsigned int)config_get_int(
                config, key_bytes_stored));
            config_set(config, key_size, size);
            config_set(config, key_status, marker_complete);
            finish_local_request(config);
            upgrade_command_executor_set_result(executor, 5u);
            state = 6u;
        } else if (state == 5u) {
            config_set(config, key_status, marker_error);
            finish_local_request(config);
            upgrade_command_executor_set_result(executor, 5u);
            state = 6u;
        }
    }
    stock_set_state(executor, state);
}

void __attribute__((section(".text.0.main")))
start(void)
{
    /* Payload linker entry; hooks and RPC registration use named symbols. */
}
