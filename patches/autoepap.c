/* iVAPS AutoEPAP: pressure response, private histories and stock-worker adapters.
 * Keep one translation unit so the small numeric helpers can be inlined without
 * a second copy of the firmware's filters, timing or waveform engine.
 */
#include "autoepap/core.c"
#include "autoepap/features.c"
#include "autoepap/history.c"
#include "autoepap/qualification.c"
#include "autoepap/projection.c"
#include "autoepap/capture.c"
#include "autoepap/integration.c"
#include "autoepap/shared.c"
