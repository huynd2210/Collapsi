cmake_minimum_required(VERSION 3.16)
project(collapsi_cpp LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(collapsi_core
  src/bitboard.cpp
  src/hash.cpp
  src/solver.cpp
)
target_include_directories(collapsi_core PUBLIC include)

add_executable(collapsi_cpp src/cli.cpp)
target_link_libraries(collapsi_cpp PRIVATE collapsi_core)

add_executable(gen_positions src/gen_positions.cpp)
target_link_libraries(gen_positions PRIVATE collapsi_core)

add_executable(solve_norm_db src/solve_norm_db.cpp)
target_link_libraries(solve_norm_db PRIVATE collapsi_core)

add_executable(list_derivations src/list_derivations.cpp)
target_link_libraries(list_derivations PRIVATE collapsi_core)


