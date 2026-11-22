// CI only: an isolated, disposable Keychain shared by two distinct release identities' builds.
#include <Security/Security.h>
#include <string.h>
#include <stdio.h>

int main(int argc, char **argv) {
    if (argc != 2) return 1;
    SecKeychainRef keychain = NULL;
    OSStatus status = SecKeychainSetUserInteractionAllowed(false);
    if (!status) status = SecKeychainOpen(argv[1], &keychain);
    const char service[] = "capybara.session-upgrade-test";
    const char account[] = "fixture";
    if (!status && GENERATION == 1) {
        status = SecKeychainAddGenericPassword(keychain, strlen(service), service,
            strlen(account), account, 5, "first", NULL);
    } else if (!status) {
        void *data = NULL;
        UInt32 size = 0;
        SecKeychainItemRef item = NULL;
        status = SecKeychainFindGenericPassword(keychain, strlen(service), service,
            strlen(account), account, &size, &data, &item);
        if (!status && (size != 5 || memcmp(data, "first", 5))) status = errSecDecode;
        if (!status) status = SecKeychainItemModifyAttributesAndData(item, NULL, 4, "next");
        if (!status) status = SecKeychainItemDelete(item);
        if (data) SecKeychainItemFreeContent(NULL, data);
        if (item) CFRelease(item);
    }
    if (keychain) CFRelease(keychain);
    if (status) fprintf(stderr, "Keychain upgrade probe %d returned %d\n", GENERATION, (int)status);
    return status != errSecSuccess;
}
