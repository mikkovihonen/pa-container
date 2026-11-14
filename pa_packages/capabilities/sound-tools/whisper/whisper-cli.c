// SPDX-License-Identifier: MIT
// Minimal dynamically linked Whisper CLI for pa-container (Fedora whisper-cpp + libsndfile)

#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include <sndfile.h>
#include <whisper.h>

#define DEFAULT_MODEL_PATH "/usr/local/share/whisper/ggml-base-q5_1.bin"

typedef enum {
    OUT_TIMESTAMPS = 0,
    OUT_TEXT_ONLY,
    OUT_SRT,
    OUT_VTT,
    OUT_JSON
} output_format_t;

static void silent_log_cb(enum ggml_log_level level, const char * text, void * user_data) {
    (void)level;
    (void)text;
    (void)user_data;
}

static void format_timestamp(int64_t t_10ms, char * buf, size_t buf_size, bool comma_sep) {
    int64_t msec = t_10ms * 10;
    int64_t hr = msec / (1000 * 60 * 60);
    msec -= hr * (1000 * 60 * 60);
    int64_t min = msec / (1000 * 60);
    msec -= min * (1000 * 60);
    int64_t sec = msec / 1000;
    msec -= sec * 1000;
    snprintf(buf, buf_size, "%02lld:%02lld:%02lld%c%03lld",
             (long long)hr, (long long)min, (long long)sec,
             comma_sep ? ',' : '.', (long long)msec);
}

static void print_json_escaped(const char * s) {
    for (const unsigned char * p = (const unsigned char *)s; *p != '\0'; ++p) {
        switch (*p) {
            case '"':  fputs("\\\"", stdout); break;
            case '\\': fputs("\\\\", stdout); break;
            case '\b': fputs("\\b", stdout);  break;
            case '\f': fputs("\\f", stdout);  break;
            case '\n': fputs("\\n", stdout);  break;
            case '\r': fputs("\\r", stdout);  break;
            case '\t': fputs("\\t", stdout);  break;
            default:
                if (*p < 0x20) {
                    printf("\\u%04x", (unsigned int)*p);
                } else {
                    putchar(*p);
                }
                break;
        }
    }
}

static void print_usage(const char * prog) {
    printf("Usage: %s [options] <audio_file_or_->\n\n", prog);
    printf("Options:\n");
    printf("  -m, --model <path>     Model path (default: %s)\n", DEFAULT_MODEL_PATH);
    printf("  -l, --language <code>  Language code, e.g. en, fi, sv, auto (default: en)\n");
    printf("  -t, --threads <N>      Number of CPU threads (default: auto)\n");
    printf("      --translate        Translate speech to English\n");
    printf("  -nt, --no-timestamps   Print plain text only without timestamps\n");
    printf("  -osrt                  Output in SRT subtitle format to stdout\n");
    printf("  -ovtt                  Output in WebVTT subtitle format to stdout\n");
    printf("  -oj                    Output in JSON format to stdout\n");
    printf("  -v, --verbose          Enable internal ggml/whisper logs on stderr\n");
    printf("      --version          Print version information and exit\n");
    printf("  -h, --help             Show this help message and exit\n");
}

int main(int argc, char ** argv) {
    const char * env_model = getenv("WHISPER_MODEL_PATH");
    const char * model_path = (env_model && env_model[0] != '\0') ? env_model : DEFAULT_MODEL_PATH;
    const char * lang = "en";
    const char * audio_path = NULL;
    output_format_t out_fmt = OUT_TIMESTAMPS;
    bool translate = false;
    bool verbose = false;

    long detected_cores = sysconf(_SC_NPROCESSORS_ONLN);
    int n_threads = (detected_cores > 0) ? (int)detected_cores : 4;
    if (n_threads > 8) {
        n_threads = 8;
    }

    for (int i = 1; i < argc; ++i) {
        if (strcmp(argv[i], "-h") == 0 || strcmp(argv[i], "--help") == 0) {
            print_usage(argv[0]);
            return 0;
        } else if (strcmp(argv[i], "--version") == 0) {
            printf("whisper-cli (pa-container, libwhisper)\n");
            return 0;
        } else if ((strcmp(argv[i], "-m") == 0 || strcmp(argv[i], "--model") == 0) && i + 1 < argc) {
            model_path = argv[++i];
        } else if ((strcmp(argv[i], "-l") == 0 || strcmp(argv[i], "--language") == 0) && i + 1 < argc) {
            lang = argv[++i];
        } else if ((strcmp(argv[i], "-t") == 0 || strcmp(argv[i], "--threads") == 0) && i + 1 < argc) {
            n_threads = atoi(argv[++i]);
            if (n_threads < 1) {
                n_threads = 1;
            }
        } else if (strcmp(argv[i], "--translate") == 0) {
            translate = true;
        } else if (strcmp(argv[i], "-nt") == 0 || strcmp(argv[i], "--no-timestamps") == 0) {
            out_fmt = OUT_TEXT_ONLY;
        } else if (strcmp(argv[i], "-osrt") == 0) {
            out_fmt = OUT_SRT;
        } else if (strcmp(argv[i], "-ovtt") == 0) {
            out_fmt = OUT_VTT;
        } else if (strcmp(argv[i], "-oj") == 0) {
            out_fmt = OUT_JSON;
        } else if (strcmp(argv[i], "-v") == 0 || strcmp(argv[i], "--verbose") == 0) {
            verbose = true;
        } else if (argv[i][0] == '-' && argv[i][1] != '\0') {
            fprintf(stderr, "whisper-cli: unknown option '%s'\n", argv[i]);
            return 1;
        } else {
            audio_path = argv[i];
        }
    }

    if (!audio_path) {
        fprintf(stderr, "whisper-cli: missing input audio file (pass -h for help)\n");
        return 1;
    }

    if (!verbose) {
        whisper_log_set(silent_log_cb, NULL);
    }

    SF_INFO sfinfo;
    memset(&sfinfo, 0, sizeof(sfinfo));
    SNDFILE * sndfile = NULL;

    if (strcmp(audio_path, "-") == 0) {
        sndfile = sf_open_fd(STDIN_FILENO, SFM_READ, &sfinfo, 0);
    } else {
        sndfile = sf_open(audio_path, SFM_READ, &sfinfo);
    }

    if (!sndfile) {
        fprintf(stderr, "whisper-cli: failed to open '%s': %s\n", audio_path, sf_strerror(NULL));
        return 1;
    }

    if (sfinfo.samplerate != WHISPER_SAMPLE_RATE) {
        fprintf(stderr,
                "whisper-cli: input sample rate is %d Hz, but %d Hz is required.\n"
                "Convert first with: sox \"%s\" -r 16000 -c 1 -b 16 /tmp/audio_16k.wav\n",
                sfinfo.samplerate, WHISPER_SAMPLE_RATE, audio_path);
        sf_close(sndfile);
        return 1;
    }

    size_t capacity = (sfinfo.frames > 0) ? (size_t)sfinfo.frames : (size_t)(WHISPER_SAMPLE_RATE * 30);
    float * pcmf32 = (float *)malloc(capacity * sizeof(float));
    int channels = sfinfo.channels;
    const size_t chunk_frames = 4096;
    float * buf = (float *)malloc(chunk_frames * (size_t)channels * sizeof(float));
    if (!pcmf32 || !buf) {
        fprintf(stderr, "whisper-cli: out of memory allocating audio buffer\n");
        free(pcmf32);
        free(buf);
        sf_close(sndfile);
        return 1;
    }

    size_t total_frames = 0;
    sf_count_t read_frames = 0;
    while ((read_frames = sf_readf_float(sndfile, buf, (sf_count_t)chunk_frames)) > 0) {
        if (total_frames + (size_t)read_frames > capacity) {
            capacity = (total_frames + (size_t)read_frames) * 2;
            float * next = (float *)realloc(pcmf32, capacity * sizeof(float));
            if (!next) {
                fprintf(stderr, "whisper-cli: out of memory growing audio buffer\n");
                free(pcmf32);
                free(buf);
                sf_close(sndfile);
                return 1;
            }
            pcmf32 = next;
        }
        if (channels == 1) {
            memcpy(pcmf32 + total_frames, buf, (size_t)read_frames * sizeof(float));
        } else {
            for (sf_count_t f = 0; f < read_frames; ++f) {
                float sum = 0.0f;
                for (int c = 0; c < channels; ++c) {
                    sum += buf[f * channels + c];
                }
                pcmf32[total_frames + (size_t)f] = sum / (float)channels;
            }
        }
        total_frames += (size_t)read_frames;
    }
    free(buf);
    sf_close(sndfile);

    struct whisper_context_params cparams = whisper_context_default_params();
    cparams.use_gpu = false;
    struct whisper_context * ctx = whisper_init_from_file_with_params(model_path, cparams);
    if (!ctx) {
        fprintf(stderr, "whisper-cli: failed to load model '%s'\n", model_path);
        free(pcmf32);
        return 1;
    }

    fprintf(stderr, "whisper-cli: model=%s samples=%zu (%.2fs) lang=%s threads=%d\n",
            model_path, total_frames, (double)total_frames / WHISPER_SAMPLE_RATE, lang, n_threads);

    struct whisper_full_params wparams = whisper_full_default_params(WHISPER_SAMPLING_GREEDY);
    wparams.n_threads = n_threads;
    wparams.translate = translate;
    wparams.print_progress = false;
    wparams.print_realtime = false;
    wparams.print_special = false;
    wparams.print_timestamps = false;

    if (strcmp(lang, "auto") == 0) {
        wparams.language = "auto";
        wparams.detect_language = false;
    } else {
        wparams.language = lang;
    }

    if (whisper_full(ctx, wparams, pcmf32, (int)total_frames) != 0) {
        fprintf(stderr, "whisper-cli: inference failed\n");
        whisper_free(ctx);
        free(pcmf32);
        return 1;
    }

    int n_segments = whisper_full_n_segments(ctx);

    if (out_fmt == OUT_VTT) {
        printf("WEBVTT\n\n");
    } else if (out_fmt == OUT_JSON) {
        printf("{\"model\":\"");
        print_json_escaped(model_path);
        printf("\",\"language\":\"");
        print_json_escaped(lang);
        printf("\",\"segments\":[");
    }

    for (int i = 0; i < n_segments; ++i) {
        const char * text = whisper_full_get_segment_text(ctx, i);
        int64_t t0 = whisper_full_get_segment_t0(ctx, i);
        int64_t t1 = whisper_full_get_segment_t1(ctx, i);
        char ts0[32];
        char ts1[32];

        switch (out_fmt) {
            case OUT_TEXT_ONLY:
                while (*text == ' ') {
                    text++;
                }
                printf("%s\n", text);
                break;
            case OUT_TIMESTAMPS:
                format_timestamp(t0, ts0, sizeof(ts0), false);
                format_timestamp(t1, ts1, sizeof(ts1), false);
                printf("[%s --> %s]  %s\n", ts0, ts1, text);
                break;
            case OUT_SRT:
                format_timestamp(t0, ts0, sizeof(ts0), true);
                format_timestamp(t1, ts1, sizeof(ts1), true);
                while (*text == ' ') {
                    text++;
                }
                printf("%d\n%s --> %s\n%s\n\n", i + 1, ts0, ts1, text);
                break;
            case OUT_VTT:
                format_timestamp(t0, ts0, sizeof(ts0), false);
                format_timestamp(t1, ts1, sizeof(ts1), false);
                while (*text == ' ') {
                    text++;
                }
                printf("%s --> %s\n%s\n\n", ts0, ts1, text);
                break;
            case OUT_JSON:
                while (*text == ' ') {
                    text++;
                }
                printf("%s{\"start_sec\":%.2f,\"end_sec\":%.2f,\"text\":\"",
                       (i > 0) ? "," : "", (double)t0 * 0.01, (double)t1 * 0.01);
                print_json_escaped(text);
                printf("\"}");
                break;
        }
    }

    if (out_fmt == OUT_JSON) {
        printf("]}\n");
    }

    whisper_free(ctx);
    free(pcmf32);
    return 0;
}