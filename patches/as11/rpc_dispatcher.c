/* Register named objects with the stock JSON RPC formatter registry. */

#include "stubs.h"
#include "rpc_object.h"

#define RPC_OBJECT_CAPACITY 8u

/* Native registration object layout expected by the stock constructor. */
typedef struct {
    const void *vtable;
    void *next;
} formatter_registration_t;

/* Single lookup slot exposed by a formatter-registry registration. */
typedef struct {
    void *(*lookup)(
        void *self,
        const char *name,
        unsigned int name_length,
        void *formatter_storage);
} registration_vtable_t;

/* Adapter constructed in the temporary formatter storage supplied by APPL. */
typedef struct {
    const void *vtable;
    const rpc_object_t *object;
} object_formatter_t;

/* Operation slots consumed by the stock Get, Set, and schema paths. */
typedef struct {
    const void *reserved_0;
    const void *reserved_1;
    int (*is_resolved)(void *self);
    int (*is_available)(void *self);
    unsigned int (*get_dataitem_var_id)(void *self);
    int (*write_value)(void *self, void *encoder);
    int (*write_schema)(void *self, void *encoder);
    int (*apply_value)(void *self, const rpc_json_span_t *value);
    int (*write_error)(
        void *self,
        void *encoder,
        const rpc_json_span_t *value);
} formatter_vtable_t;

/* The patcher writes provider descriptors followed by a sentinel. */
volatile const unsigned int
rpc_object_table[RPC_OBJECT_CAPACITY + 1u]
    __attribute__((used, section(".rodata.params"))) = {
        0xFFFFFFFFu,
        0xFFFFFFFFu,
        0xFFFFFFFFu,
        0xFFFFFFFFu,
        0xFFFFFFFFu,
        0xFFFFFFFFu,
        0xFFFFFFFFu,
        0xFFFFFFFFu,
        0xFFFFFFFFu,
    };

static int formatter_is_resolved(void *self)
{
    /* A table match already resolved the object; providers gate availability. */
    return 1;
}

static int formatter_is_available(void *self)
{
    const rpc_object_t *object = ((object_formatter_t *)self)->object;

    if (object->is_available == 0)
        return 1;
    return object->is_available(object->context);
}

static unsigned int formatter_get_dataitem_var_id(void *self)
{
    return ((object_formatter_t *)self)->object->dataitem_var_id;
}

static int formatter_write_value(void *self, void *encoder)
{
    const rpc_object_t *object = ((object_formatter_t *)self)->object;

    return object->write_value(object->context, encoder);
}

static int formatter_write_schema(void *self, void *encoder)
{
    static const unsigned char empty_schema[] = "{}";
    const rpc_object_t *object = ((object_formatter_t *)self)->object;
    const rpc_json_span_t span = {
        empty_schema,
        empty_schema + sizeof(empty_schema) - 1u,
    };

    if (object->write_schema != 0)
        return object->write_schema(object->context, encoder);
    return json_encoder_write_raw_span(self, encoder, &span);
}

static int formatter_apply_value(
    void *self, const rpc_json_span_t *value)
{
    const rpc_object_t *object = ((object_formatter_t *)self)->object;

    if (object->apply_value == 0)
        return 0;
    return object->apply_value(object->context, value);
}

static int formatter_write_error(
    void *self,
    void *encoder,
    const rpc_json_span_t *value)
{
    const rpc_object_t *object = ((object_formatter_t *)self)->object;

    if (object->write_error != 0) {
        return object->write_error(object->context, encoder, value);
    }
    return json_encoder_write_raw_span(self, encoder, value);
}

static const formatter_vtable_t formatter_vtable = {
    0,
    0,
    formatter_is_resolved,
    formatter_is_available,
    formatter_get_dataitem_var_id,
    formatter_write_value,
    formatter_write_schema,
    formatter_apply_value,
    formatter_write_error,
};

static int name_equals(
    const rpc_object_t *object,
    const char *name,
    unsigned int name_length)
{
    unsigned int index;

    if (name_length != object->name_length)
        return 0;
    for (index = 0; index < name_length; ++index) {
        if (name[index] != object->name[index])
            return 0;
    }
    return 1;
}

static void *registration_lookup(
    void *self,
    const char *name,
    unsigned int name_length,
    void *formatter_storage)
{
    unsigned int index;

    if (formatter_storage == 0)
        return 0;

    /* Match without allocating; APPL owns the formatter_storage lifetime. */
    for (index = 0; index < RPC_OBJECT_CAPACITY + 1u; ++index) {
        unsigned int address = rpc_object_table[index];
        const rpc_object_t *object;
        object_formatter_t *formatter;

        if (address == 0 || address == 0xFFFFFFFFu)
            break;
        object = (const rpc_object_t *)address;
        if (name_equals(object, name, name_length)) {
            formatter = (object_formatter_t *)formatter_storage;
            formatter->vtable = &formatter_vtable;
            formatter->object = object;
            return formatter;
        }
    }
    return 0;
}

static const registration_vtable_t registration_vtable = {
    registration_lookup,
};

void __attribute__((section(".text.0.main")))
start(void)
{
    formatter_registration_t *registration;

    /* This replaces the stock init entry, so preserve its constructor first. */
    rpc_profile_json_formatter_registry_ctor();

    /* The stock registration constructor links this object into the registry. */
    registration = (formatter_registration_t *)heap_alloc(
        (unsigned int)sizeof(*registration));
    if (registration == 0)
        return;

    rpc_profile_json_formatter_registration_ctor(registration);
    /* Keep the stock registration linkage and replace only lookup behavior. */
    registration->vtable = &registration_vtable;
}
