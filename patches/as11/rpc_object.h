#ifndef AIRBREAK_AS11_RPC_OBJECT_H
#define AIRBREAK_AS11_RPC_OBJECT_H

/* Stock formatter sentinel for an object without a schema DataItem. */
#define RPC_OBJECT_NO_DATAITEM 0x7FFFu

/* Raw JSON value supplied by the stock parser; end is one past the last byte. */
typedef struct {
    const unsigned char *begin;
    const unsigned char *end;
} rpc_json_span_t;

/* Callback return values follow the stock formatter convention: nonzero means
 * available, written, or accepted as appropriate for that callback.
 */
typedef int (*rpc_object_is_available_t)(void *context);
typedef int (*rpc_object_write_json_t)(void *context, void *encoder);
typedef int (*rpc_object_apply_json_t)(
    void *context, const rpc_json_span_t *value);
typedef int (*rpc_object_write_error_t)(
    void *context,
    void *encoder,
    const rpc_json_span_t *value);

/*
 * One named object exposed through the stock Get and Set methods.
 *
 * write_value emits the current value used by Get and successful Set replies.
 * apply_value receives the candidate JSON value from Set and returns nonzero
 * after accepting it. Omitting apply_value makes the object read-only.
 * dataitem_var_id is used by stock schema handling; callbacks still own all
 * reads and writes performed by the provider.
 */
typedef struct {
    /* Name storage and context must remain valid for the process lifetime. */
    const char *name;
    unsigned short name_length;
    unsigned short dataitem_var_id;
    void *context;

    /* Missing optional callbacks use the defaults implemented by dispatcher. */
    rpc_object_is_available_t is_available;
    rpc_object_write_json_t write_value;
    rpc_object_write_json_t write_schema;
    rpc_object_apply_json_t apply_value;
    /* Optional Set-error formatter; the default echoes the rejected value. */
    rpc_object_write_error_t write_error;
} rpc_object_t;

#endif
