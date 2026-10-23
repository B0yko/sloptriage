cmake_minimum_required(VERSION 3.13)
project(parsekit VERSION 1.2.0 LANGUAGES C)

set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED ON)

add_library(parsekit src/buf.c src/util.c src/url.c src/query.c src/header.c)
target_include_directories(parsekit
  PUBLIC $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include> $<INSTALL_INTERFACE:include>
  PRIVATE src)
target_compile_options(parsekit PRIVATE -Wall -Wextra)

add_executable(parsekit-cli cli/parsekit.c)
set_target_properties(parsekit-cli PROPERTIES OUTPUT_NAME parsekit)
target_link_libraries(parsekit-cli PRIVATE parsekit)

enable_testing()
add_executable(parsekit-tests tests/test_parsekit.c)
target_link_libraries(parsekit-tests PRIVATE parsekit)
add_test(NAME parsekit-tests COMMAND parsekit-tests)

install(TARGETS parsekit parsekit-cli
  ARCHIVE DESTINATION lib LIBRARY DESTINATION lib RUNTIME DESTINATION bin)
install(FILES include/parsekit.h DESTINATION include)
