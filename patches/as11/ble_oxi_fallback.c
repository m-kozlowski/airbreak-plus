/* Retry an unbonded PLX peer once without security after pairing fails. */

#include "stubs.h"

/* Native OXI client layout. 0x76 is padding between the incompatibility
 * flag (0x75) and connection context (0x78), owned by this patch. Queueing
 * a new request initializes it; native reset leaves it untouched. */
#define STATE_OFFSET          0x0Cu
/* APPX 8.7 moves the sample sink; 0x28 holds the result callback there. */
#if defined(APPX_VER_8_7_0)
#define SAMPLE_SINK_OFFSET    0x2Cu
#else
#define SAMPLE_SINK_OFFSET    0x28u
#endif
#define CALLBACK_OFFSET       0x30u
#define INVALID_BOND_OFFSET   0x5Eu
#define CLOSING_OFFSET        0x6Au
#define CONNECTED_OFFSET      0x6Bu
#define ADDRESS_OFFSET        0x6Cu
#define ADDRESS_TYPE_OFFSET   0x72u
#define CONNECTION_OFFSET     0x73u
#define BOND_OFFSET           0x74u
#define FALLBACK_OFFSET       0x76u
#define CONTEXT_OFFSET        0x78u
#define CLIENT_INTERFACE_OFFSET 8u
#define CONTINUOUS_HANDLE_OFFSET 0x66u
#define SINK_REJECT_MASK_OFFSET 8u
#define MEASUREMENT_ONGOING    0x0020u

#define NORMAL               0u
#define RETRY_CLOSING        1u
#define RETRY_UNSECURED      2u
#define STATE_IDLE           0u
#define STATE_SECURITY       5u
#define STATE_SECURITY_WAIT  6u
#define STATE_PARAMETERS    15u
#define STATE_CONNECTED     19u

/* BGAPI event IDs, excluding the variable payload length. */
#define EVENT_MASK           0xFFFF00F8u
#define CONNECTION_OPENED    0x000800A0u
#define CONNECTION_CLOSED    0x010800A0u
#define BONDING_FAILED       0x040F00A0u
#define CHARACTERISTIC_VALUE 0x040900A0u

static unsigned int state(const unsigned char *client)
{
    return *(const unsigned int *)(client + STATE_OFFSET);
}

void ble_oxi_fallback_queue_connect(void *self, unsigned int address_lo,
    unsigned int address_hi, unsigned char address_type, unsigned int context)
{
    unsigned char *client = self;
    client[FALLBACK_OFFSET] = NORMAL;
    ble_oxi_gatt_client_queue_connect(self, address_lo, address_hi, address_type, context);
}

void ble_oxi_fallback_queue_connect_adjustor(void *self, unsigned int address_lo,
    unsigned int address_hi, unsigned char address_type, unsigned int context)
{
    ble_oxi_fallback_queue_connect((unsigned char *)self - CLIENT_INTERFACE_OFFSET,
        address_lo, address_hi, address_type, context);
}

void ble_oxi_fallback_disconnect(void *self)
{
    unsigned char *client = self;
    /* User cancellation and native error cleanup also cancel a pending retry. */
    client[FALLBACK_OFFSET] = NORMAL;
    ble_oxi_gatt_client_request_disconnect(self);
}

void ble_oxi_fallback_disconnect_adjustor(void *self)
{
    ble_oxi_fallback_disconnect((unsigned char *)self - CLIENT_INTERFACE_OFFSET);
}

static void reconnect_unsecured(unsigned char *client)
{
    unsigned int address_lo = *(unsigned int *)(client + ADDRESS_OFFSET);
    unsigned int address_hi = *(unsigned short *)(client + ADDRESS_OFFSET + 4);
    unsigned char address_type = client[ADDRESS_TYPE_OFFSET];
    unsigned int context = *(unsigned int *)(client + CONTEXT_OFFSET);

    if (client[CONNECTED_OFFSET])
        callback_notifier_invoke(client + CALLBACK_OFFSET, 6); /* Disconnected */

    /* Do not report a terminal result to the OXI controller between attempts.
     * Its original connection deadline and cancellation remain in force. */
    ble_oxi_gatt_client_reset_connection_state(client);
    ble_oxi_gatt_client_queue_connect(client, address_lo, address_hi, address_type, context);
    client[FALLBACK_OFFSET] = RETRY_UNSECURED;
}

void __attribute__((section(".text.0.main")))
start(void *self, const unsigned int *event)
{
    unsigned char *client = self;
    unsigned int kind = event[0] & EVENT_MASK;

    /* Other links, including the phone/RPC link, retain stock dispatch. */
    if (state(client) == STATE_IDLE ||
            ble_stack_event_connection_id(event) != client[CONNECTION_OFFSET]) {
        ble_oxi_gatt_client_on_stack_event(client, event);
        return;
    }

    if (kind == CONNECTION_CLOSED && client[FALLBACK_OFFSET] == RETRY_CLOSING) {
        reconnect_unsecured(client);
        return;
    }

    if (kind == BONDING_FAILED && state(client) == STATE_SECURITY_WAIT &&
            !client[CLOSING_OFFSET] && client[FALLBACK_OFFSET] == NORMAL &&
            client[BOND_OFFSET] == client[INVALID_BOND_OFFSET]) {
        callback_notifier_invoke(client + CALLBACK_OFFSET, 3); /* Pairing failed */
        client[FALLBACK_OFFSET] = RETRY_CLOSING;
        /* Use the original close, not our cancellation wrapper. Reconnect
         * on the close event even if the peer has already terminated the link. */
        ble_oxi_gatt_client_request_disconnect(client);
        return;
    }

    if (kind == CONNECTION_CLOSED)
        client[FALLBACK_OFFSET] = NORMAL;

    if (kind == CHARACTERISTIC_VALUE && client[FALLBACK_OFFSET] == RETRY_UNSECURED &&
            !client[CLOSING_OFFSET] && state(client) == STATE_CONNECTED &&
            *(const unsigned short *)((const unsigned char *)event + 5) ==
                *(unsigned short *)(client + CONTINUOUS_HANDLE_OFFSET)) {
        unsigned char *sink = *(unsigned char **)(client + SAMPLE_SINK_OFFSET);
        unsigned short *reject = (unsigned short *)(sink + SINK_REJECT_MASK_OFFSET);
        unsigned short saved = *reject;

        /* Medisana sets Measurement Ongoing on its continuous readings.
         * Relax only that status for this fallback sample; native parsing,
         * other status bits and non-finite value checks remain in force. */
        *reject = saved & ~MEASUREMENT_ONGOING;
        ble_oxi_gatt_client_on_stack_event(client, event);
        *reject = saved;
        return;
    }

    ble_oxi_gatt_client_on_stack_event(client, event);

    if (kind == CONNECTION_OPENED && client[FALLBACK_OFFSET] == RETRY_UNSECURED &&
            !client[CLOSING_OFFSET] && state(client) == STATE_SECURITY) {
        if (client[BOND_OFFSET] != client[INVALID_BOND_OFFSET]) {
            /* A bond discovered on reopening still follows native security. */
            client[FALLBACK_OFFSET] = NORMAL;
        } else {
            /* Enter the stock post-security path: parameters, discovery,
             * Features, Continuous Measurement, then notification enable. */
            *(unsigned int *)(client + STATE_OFFSET) = STATE_PARAMETERS;
        }
    }
}
