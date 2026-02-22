# Patched replacement for the cmake 3.28 cross-compilation regression.
#
# cmake 3.28 moved CMAKE_C/CXX_STANDARD_COMPUTED_DEFAULT population into the
# ABI-detection step that runs a compiled test binary.  For cross-compilers
# with CMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY the binary is never run,
# so the variable is never set, and cmake 3.28 fatals.
#
# This file reproduces cmake 3.29's fix: fall back to the caller-supplied
# default_std instead of fataling.  Everything else in the macro is identical
# to the original so downstream consumers of CMAKE_C/CXX_STANDARD_DEFAULT are
# unaffected.

macro(__compiler_check_default_language_standard lang min_version default_std)
  if(CMAKE_${lang}_COMPILER_VERSION VERSION_GREATER_EQUAL min_version)
    if(NOT DEFINED CMAKE_${lang}_STANDARD_COMPUTED_DEFAULT)
      # cmake 3.28 would fatal here; cmake 3.29 sets a safe default instead.
      set(CMAKE_${lang}_STANDARD_COMPUTED_DEFAULT "${default_std}")
      set(CMAKE_${lang}_EXTENSIONS_COMPUTED_DEFAULT ON)
    endif()
    set(CMAKE_${lang}_STANDARD_DEFAULT ${CMAKE_${lang}_STANDARD_COMPUTED_DEFAULT})
    set(CMAKE_${lang}_EXTENSIONS_DEFAULT ${CMAKE_${lang}_EXTENSIONS_COMPUTED_DEFAULT})
  endif()
endmacro()
