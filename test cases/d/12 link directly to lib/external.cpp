/*
 * Yes this is all mindboggling too compilcated, but this forces boost thread to
 * be linked and not ignored by --as-needed
 */
#include <boost/thread/thread.hpp>
#include <boost/lockfree/queue.hpp>

namespace {

boost::lockfree::queue<const char *> cQueue{1};
boost::lockfree::queue<int> iQueue{1};

int safe_char_to_int(const char * value) noexcept {
    try {
        return std::stoi(value);
    } catch (std::invalid_argument & e) {
        return 0;
    }
}

void sender() {
    const char * v{};
    cQueue.pop(v);
    iQueue.push(safe_char_to_int(v));
}

}

int
char_to_int(const char * const value) {
    cQueue.push(value);
    boost::thread t{sender};
    t.join();

    int i{};
    iQueue.pop(i);
    return i;
}
