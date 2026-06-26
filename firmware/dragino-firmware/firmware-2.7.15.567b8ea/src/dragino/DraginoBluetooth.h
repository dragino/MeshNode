#pragma once



#include "configuration.h"
#include "concurrency/OSThread.h"


#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
namespace dragino {

struct AtCmd {
    const char *cmd;
    const char *expect;
    uint32_t timeoutMs;
};

class DraginoBluetooth : public concurrency::OSThread
{
  public:
    enum State {
        HIBERNATING,
        BOOTING,
        INITIALIZING,
        ADVERTISING,
        CONNECTED,
    };

    DraginoBluetooth();

    void toggle();

    bool isConnected() const;
    State getState() const { return state_; }
    void shutdown();
    void prepareForSleep();
    bool canSleep() const;
    void resumeAfterStop(bool wakeForUse);

  protected:
    virtual int32_t runOnce() override;

  private:
    State state_ = HIBERNATING;
    uint32_t stateEnteredMs_ = 0;
    uint8_t initRetryCount_ = 0;
    bool wakeForUse_ = false;

    // --- GPIO helpers ---
    void pulseRst(uint32_t ms = 200);
    void pulseKey(uint32_t ms = 200);
    void setSleepPins();

    // --- AT window ---
    void beginAtWindow(uint32_t baud);
    void endAtWindow();
    void switchBaud(uint32_t baud);
    void drain();

    // --- AT layer ---
    // Send one AT command and wait for a line containing `expect`.
    // Must be called inside an AT exclusive window.
    bool sendAt(const char *cmd, const char *expect, uint32_t timeoutMs = 500);

    // Send one AT command and collect response lines.
    bool sendAtCollect(const char *cmd, char *outBuf, size_t outBufSize, uint32_t timeoutMs = 500);

    // Query current module name via AT+NAME and parse +NAME=<name>.
    bool queryBtName(char *nameBuf, size_t nameBufSize);

    // Run a sequence of AT commands; stops on first failure.
    bool runAtSequence(const AtCmd *cmds, size_t count);

    // --- State machine helpers ---
    void enterState(State s);
    void doWakeup();       // RST pulse -> BOOTING
    void doHibernate();    // AT+PWRM2 -> HIBERNATING

    // --- AT sequences ---
    bool runInitSequence();   // 9600->115200, name, etc.
    bool runHibernateSequence();
};

extern DraginoBluetooth *draginoBluetooth;

} // namespace dragino

#endif // defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
