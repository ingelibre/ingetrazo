// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 IngeTrazo contributors.
//
// Qt's item views and QAccessibleCache own accessible interfaces; their native
// Cocoa wrappers must not delete them. This includes real cells as well as
// synthesized rows/columns/cells sharing their parent's accessibility ID.
// Backport the ownership behavior proposed in QTBUG-149612 / qtbase 772484:
// https://codereview.qt-project.org/c/qt/qtbase/+/772484
// Keep Qt 6.11.2's native array releases, invalidation notifications and super
// dealloc, while preventing interface deletion from both cleanup entry points.
// The Python loader pins this shim to PySide6 and Qt 6.11.2. Remove it once the
// packaged Qt contains the upstream fix; see docs/macos-accessibility.md.

#import <Foundation/Foundation.h>
#import <objc/runtime.h>

#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

typedef void (*DeallocImplementation)(id, SEL);

static DeallocImplementation originalDealloc;
static ptrdiff_t axidOffset;
static BOOL installed;
static const char *lastError = "not installed";

static void guardedDealloc(id object, SEL selector)
{
    // Qt 6.11.2's original dealloc only uses axid for deleteInterface(). Zero
    // is never a registered QAccessible ID, so that call becomes a no-op.
    // Do this for real cells too: deleting their interfaces would leave the
    // item view's childToId cache stale after native row/column arrays expire.
    const uint32_t noInterface = 0;
    memcpy((char *)object + axidOffset, &noInterface, sizeof(noInterface));
    originalDealloc(object, selector);
}

static void guardedCleanup(id klass, SEL selector, NSArray *elements)
{
    // Upstream removes removeElementsFromCache: and its callers altogether.
    // Making it a no-op has the same ownership effect without replacing
    // invalidate or reproducing Qt's native retain/release implementation.
    (void)klass;
    (void)selector;
    (void)elements;
}

static Method ownMethod(Class klass, SEL selector)
{
    unsigned int count = 0;
    Method *methods = class_copyMethodList(klass, &count);
    Method found = NULL;
    for (unsigned int i = 0; i < count; ++i) {
        if (sel_isEqual(method_getName(methods[i]), selector)) {
            found = methods[i];
            break;
        }
    }
    free(methods);
    return found;
}

static BOOL matchesType(char *actual, const char *expected)
{
    const BOOL matches = actual && strcmp(actual, expected) == 0;
    free(actual);
    return matches;
}

static BOOL hasSignature(Method method, unsigned int arguments, const char *result)
{
    if (!method || method_getNumberOfArguments(method) != arguments)
        return NO;
    if (!matchesType(method_copyReturnType(method), result))
        return NO;
    char *selfType = method_copyArgumentType(method, 0);
    const BOOL objectSelf = selfType && (strcmp(selfType, "@") == 0
                                       || strcmp(selfType, "#") == 0);
    free(selfType);
    if (!objectSelf || !matchesType(method_copyArgumentType(method, 1), ":"))
        return NO;
    return arguments == 2 || matchesType(method_copyArgumentType(method, 2), "@");
}

__attribute__((visibility("default")))
const char *ingetrazo_cocoa_accessibility_fix_error(void)
{
    return lastError;
}

__attribute__((visibility("default")))
int ingetrazo_install_cocoa_accessibility_fix(void)
{
    if (![NSThread isMainThread]) {
        lastError = "Cocoa accessibility fix must be installed on the main thread";
        return 1;
    }
    if (installed)
        return 0;

    Class klass = objc_getClass("QMacAccessibilityElement");
    if (!klass) {
        lastError = "QMacAccessibilityElement is unavailable; create a Cocoa QApplication first";
        return 2;
    }
    SEL deallocSelector = sel_registerName("dealloc");
    SEL cleanupSelector = sel_registerName("removeElementsFromCache:");
    // Never replace an inherited NSObject implementation by accident.
    Method dealloc = ownMethod(klass, deallocSelector);
    Method cleanup = ownMethod(object_getClass(klass), cleanupSelector);
    if (!hasSignature(dealloc, 2, "v") || !hasSignature(cleanup, 3, "v")) {
        lastError = "Unsupported QMacAccessibilityElement cleanup method signatures";
        return 3;
    }

    Ivar axid = class_getInstanceVariable(klass, "axid");
    const char *axidType = axid ? ivar_getTypeEncoding(axid) : NULL;
    if (!axidType || strcmp(axidType, "I") != 0) {
        lastError = "Unsupported QMacAccessibilityElement accessibility ID type";
        return 4;
    }
    axidOffset = ivar_getOffset(axid);
    const size_t instanceSize = class_getInstanceSize(klass);
    if (axidOffset < (ptrdiff_t)sizeof(void *) || instanceSize < sizeof(uint32_t)
            || (size_t)axidOffset > instanceSize - sizeof(uint32_t)) {
        lastError = "QMacAccessibilityElement accessibility ID is outside the instance";
        return 4;
    }
    originalDealloc = (DeallocImplementation)method_getImplementation(dealloc);
    if (!originalDealloc || !method_getImplementation(cleanup)) {
        lastError = "QMacAccessibilityElement cleanup implementation is unavailable";
        return 5;
    }

    // All checks succeed before either method is changed. Both hooks are
    // needed: invalidate and dealloc invoke the class cleanup method, while
    // dealloc also tries to delete its own interface directly.
    method_setImplementation(cleanup, (IMP)guardedCleanup);
    method_setImplementation(dealloc, (IMP)guardedDealloc);
    installed = YES;
    lastError = "";
    return 0;
}
