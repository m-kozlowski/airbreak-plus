// Author: noombs @ Discord

// float * const fvars = (void*) 0x2000e948;
// int * const ivars = (void*) 0x2000e750;

void start() {
    // Suppress the ASV backup rate
    //
    int* isNotBreathingPtr = (int*)0x2000e808;
    float* breathPercentagePtr = (float*)0x2000ea9c;
    // float* breathPercentagePtr = &fvars[0xD3]

    if (*isNotBreathingPtr == 1 && *breathPercentagePtr > 0.98f) {
        *breathPercentagePtr = 0.98f;
    }

    // Execute the ASV task
    //
    void (*asvFunctionPtr)() = (void*)0x80e3465;
    asvFunctionPtr();
}