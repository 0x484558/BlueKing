const PROTO_FILE: &str = "../proto/blueking.proto";

fn main() {
    // if let Ok(protoc) = protoc_bin_vendored::protoc_bin_path() {
    //     // SAFETY: build script configuration for protoc lookup.
    //     unsafe {
    //         env::set_var("PROTOC", protoc);
    //     }
    // }

    // Resolve protoc path for both Rust and Python generation.
    // let protoc_path = env::var("PROTOC").unwrap_or_else(|_| "protoc".to_string());

    // generate_python_protos(&protoc_path);

    let proto_path = std::path::PathBuf::from(PROTO_FILE).canonicalize().unwrap();
    let proto_dir = proto_path.parent().unwrap();

    tonic_build::configure()
        .compile_protos(&[proto_path.as_path()], &[proto_dir])
        .expect("failed to compile protobuf definitions");

    println!("cargo:rerun-if-changed={}", PROTO_FILE);
    // println!("cargo:rerun-if-env-changed=PROTOC");
    // println!("cargo:rerun-if-env-changed=PROTOC_GEN_GRPC_PYTHON");
    // println!("cargo:rerun-if-env-changed=PYTHON");
    // println!("cargo:rerun-if-changed=pysrc/blueking/proto/blueking_pb2.py");
    // println!("cargo:rerun-if-changed=pysrc/blueking/proto/blueking_pb2_grpc.py");
}

// fn generate_python_protos(protoc: &str) {
//     const PYTHON_OUT: &str = "pysrc/blueking/proto";
//     std::fs::create_dir_all(PYTHON_OUT).expect("failed to create python proto output dir");

//     let python = env::var("PYTHON").unwrap_or_else(|_| "python3".to_string());

//     // Always generate plain python stubs (no plugin required).
//     let py_status = std::process::Command::new(protoc)
//         .args([
//             "-I",
//             "proto",
//             &format!("--python_out={PYTHON_OUT}"),
//             PROTO_FILE,
//         ])
//         .status();
//     match py_status {
//         Ok(status) if status.success() => {}
//         Ok(status) => {
//             panic!(
//                 "protoc python_out exited with {status}. Ensure protobuf-compiler is installed."
//             );
//         }
//         Err(err) => panic!("protoc python_out failed to start: {err}"),
//     };

//     // Generate grpc stubs; require a plugin.
//     let mut grpc_generated = false;

//     // Prefer grpc_tools.protoc if available.
//     let grpc_tools = std::process::Command::new(&python)
//         .args([
//             "-m",
//             "grpc_tools.protoc",
//             "-I",
//             "proto",
//             &format!("--python_out={PYTHON_OUT}"),
//             &format!("--grpc_python_out={PYTHON_OUT}"),
//             PROTO_FILE,
//         ])
//         .status();

//     match grpc_tools {
//         Ok(status) if status.success() => grpc_generated = true,
//         _ => {}
//     }

//     if !grpc_generated {
//         // Fallback to protoc + plugin path (env or standard locations).
//         let plugin = env::var("PROTOC_GEN_GRPC_PYTHON").ok().or_else(|| {
//             [
//                 "/usr/bin/grpc_python_plugin",
//                 "/usr/local/bin/grpc_python_plugin",
//             ]
//             .iter()
//             .map(|p| p.to_string())
//             .find(|p| Path::new(p).exists())
//         });

//         let plugin = plugin.unwrap_or_else(|| {
//             panic!(
//                 "grpc_python_plugin not found; install grpcio-tools or set PROTOC_GEN_GRPC_PYTHON"
//             )
//         });

//         let status = std::process::Command::new(protoc)
//             .args([
//                 "-I",
//                 "proto",
//                 &format!("--python_out={PYTHON_OUT}"),
//                 &format!("--grpc_python_out={PYTHON_OUT}"),
//                 &format!("--plugin=protoc-gen-grpc_python={plugin}"),
//                 PROTO_FILE,
//             ])
//             .status()
//             .expect("failed to start protoc for grpc_python_out");

//         if !status.success() {
//             panic!("protoc grpc python stub generation exited with {status}");
//         }

//         grpc_generated = true;
//     }

//     if !grpc_generated {
//         panic!(
//             "failed to generate python protobuf stubs; ensure grpcio-tools or grpc_python_plugin is installed"
//         );
//     }

//     // Ensure grpc stubs exist.
//     let pb2_grpc = format!("{PYTHON_OUT}/blueking_pb2_grpc.py");
//     if !Path::new(&pb2_grpc).exists() {
//         panic!("python gRPC stubs missing after generation: {}", pb2_grpc);
//     }
// }
