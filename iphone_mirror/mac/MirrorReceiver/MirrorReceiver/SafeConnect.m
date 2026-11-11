#import "SafeConnect.h"

BOOL MirrorConnectPlayer(AVAudioEngine *engine, AVAudioPlayerNode *player, AVAudioFormat *format) {
    @try {
        [engine connect:player to:engine.mainMixerNode format:format];
        return YES;
    } @catch (NSException *exception) {
        return NO;
    }
}
