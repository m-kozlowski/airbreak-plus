/* Expose build and patch metadata as the read-only AirbreakInfo RPC object. */

#include "stubs.h"
#include "rpc_object.h"

#define AIRBREAK_INFO_JSON_CAPACITY 2048u

/* Finalization writes the complete JSON value and its exact encoded length. */
volatile const unsigned char airbreak_info_json[AIRBREAK_INFO_JSON_CAPACITY]
    __attribute__((used, section(".rodata.manifest"))) = {0};
volatile const unsigned int airbreak_info_json_length
    __attribute__((used, section(".rodata.params"))) = 0u;

static int airbreak_info_write_value(void *context, void *encoder)
{
    const rpc_json_span_t span = {
        (const unsigned char *)airbreak_info_json,
        (const unsigned char *)airbreak_info_json + airbreak_info_json_length,
    };

    return json_encoder_write_raw_span(context, encoder, &span);
}

static int airbreak_info_write_schema(void *context, void *encoder)
{
    static const unsigned char schema[] =
        "{\"type\":\"object\",\"readOnly\":true}";
    const rpc_json_span_t span = {
        schema,
        schema + sizeof(schema) - 1u,
    };

    return json_encoder_write_raw_span(context, encoder, &span);
}

static const char airbreak_info_name[] = "AirbreakInfo";

const rpc_object_t airbreak_info_rpc_object
    __attribute__((used, section(".rodata.rpc_object"))) = {
        .name = airbreak_info_name,
        .name_length = sizeof(airbreak_info_name) - 1u,
        /* This object has its own schema and no backing firmware DataItem. */
        .dataitem_var_id = RPC_OBJECT_NO_DATAITEM,
        .write_value = airbreak_info_write_value,
        .write_schema = airbreak_info_write_schema,
    };

void __attribute__((section(".text.0.main")))
start(void)
{
    /* Payload linker entry; rpc_object registration uses the descriptor. */
}
