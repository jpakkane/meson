/*
 * SPDX-License-Identifier: BSD-3-Clause
 * Copyright (c) 2010, Larry Olson
 * Copyright © 2024 Intel Corporation
 *
 * Taken from: https://github.com/loarabia/Clang-tutorial/blob/master/CItutorial2.cpp
 *
 * With updates for LLVM and Clang 18
 */

#include "llvm/Config/llvm-config.h"

#if LLVM_VERSION_MAJOR >= 18
#include "llvm/TargetParser/Host.h"
#else
#include "llvm/Support/Host.h"
#endif
#include "llvm/ADT/IntrusiveRefCntPtr.h"

#include "clang/Basic/DiagnosticOptions.h"
#include "clang/Frontend/TextDiagnosticPrinter.h"
#include "clang/Frontend/CompilerInstance.h"
#include "clang/Basic/TargetOptions.h"
#include "clang/Basic/TargetInfo.h"
#include "clang/Basic/FileManager.h"
#include "clang/Basic/SourceManager.h"
#include "clang/Lex/Preprocessor.h"
#include "clang/Basic/Diagnostic.h"

#include <iostream>

/******************************************************************************
 *
 *****************************************************************************/
int main(int argc, const char * argv[])
{
    using clang::CompilerInstance;
    using clang::TargetOptions;
    using clang::TargetInfo;
#if LLVM_VERSION_MAJOR >= 18
    using clang::FileEntryRef;
#else
    using clang::FileEntry;
#endif
    using clang::Token;
    using clang::DiagnosticOptions;
    using clang::TextDiagnosticPrinter;

    if (argc != 2) {
        std::cerr << "Need exactly 2 arguments." << std::endl;
        return 1;
    }

    CompilerInstance ci;
    DiagnosticOptions diagnosticOptions;
    ci.createDiagnostics();

    std::shared_ptr<clang::TargetOptions> pto = std::make_shared<clang::TargetOptions>();
    pto->Triple = llvm::sys::getDefaultTargetTriple();
    TargetInfo *pti = TargetInfo::CreateTargetInfo(ci.getDiagnostics(), pto);
    ci.setTarget(pti);

    ci.createFileManager();
    ci.createSourceManager(ci.getFileManager());
    ci.createPreprocessor(clang::TU_Complete);


#if LLVM_VERSION_MAJOR >= 18
    const FileEntryRef pFile = ci.getFileManager().getFileRef(argv[1]).get();
#else
    const FileEntry *pFile = ci.getFileManager().getFile(argv[1]).get();
#endif
    ci.getSourceManager().setMainFileID( ci.getSourceManager().createFileID( pFile, clang::SourceLocation(), clang::SrcMgr::C_User));
    ci.getPreprocessor().EnterMainSourceFile();
    ci.getDiagnosticClient().BeginSourceFile(ci.getLangOpts(),
                                             &ci.getPreprocessor());
    Token tok;
    bool err;
    do {
        ci.getPreprocessor().Lex(tok);
        err = ci.getDiagnostics().hasErrorOccurred();
        if (err) break;
        ci.getPreprocessor().DumpToken(tok);
        std::cerr << std::endl;
    } while ( tok.isNot(clang::tok::eof));
    ci.getDiagnosticClient().EndSourceFile();

    return err ? 1 : 0;
}
