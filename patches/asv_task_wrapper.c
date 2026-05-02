// Author: noombs @ Discord

extern int isNotBreathingPtr;
extern float breathPercentagePtr;
extern void asv_task_function(void);

void start() {
    // Suppress the ASV backup rate
    if (isNotBreathingPtr == 1 && breathPercentagePtr > 0.98f) {
        breathPercentagePtr = 0.98f;
    }

    // Execute the ASV task
    asv_task_function();
}
