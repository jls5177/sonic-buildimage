#include <Python.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <errno.h>
#include <string.h>

#define IDEBUG(...) printf(__VA_ARGS__)
//#define IDEBUG(...)

#define FPGA_RESOURCE_LENGTH 0x8000
#define MAX_FPGAS 2

static const char *fpga_resource_nodes[MAX_FPGAS] = {
    "/sys/devices/pci0000:00/0000:00:03.0/0000:05:00.0/resource0",
    "/sys/devices/pci0000:00/0000:00:03.3/0000:08:00.0/resource0"
};

static int hw_handle[MAX_FPGAS] = { -1, -1 };
static void *io_base[MAX_FPGAS] = { NULL, NULL };

static PyObject *fbfpgaio_hw_init(PyObject *self, PyObject *args)
{
    unsigned int index = MAX_FPGAS; /* sentinel = init all */
    if (!PyArg_ParseTuple(args, "|I", &index)) {
        return NULL;
    }

    if (index == MAX_FPGAS) {
        /* initialize all FPGAs */
        for (unsigned int i = 0; i < MAX_FPGAS; i++) {
            if (hw_handle[i] != -1 && io_base[i] && io_base[i] != MAP_FAILED) {
                continue;
            }

            hw_handle[i] = open(fpga_resource_nodes[i], O_RDWR | O_SYNC);
            if (hw_handle[i] == -1) {
                IDEBUG("[ERROR] %s: open hw resource node %s\n", __func__, fpga_resource_nodes[i]);
                Py_RETURN_FALSE;
            }
            IDEBUG("[PASS] %s: open hw resource node %s\n", __func__, fpga_resource_nodes[i]);

            io_base[i] = mmap(NULL, FPGA_RESOURCE_LENGTH, PROT_READ | PROT_WRITE, MAP_SHARED | MAP_NORESERVE, hw_handle[i], 0);
            if (io_base[i] == MAP_FAILED) {
                IDEBUG("[ERROR] %s: mapping resource node %s\n", __func__, fpga_resource_nodes[i]);
                perror("map_failed");
                fprintf(stderr, "%d %s\n", errno, strerror(errno));
                close(hw_handle[i]); hw_handle[i] = -1;
                Py_RETURN_FALSE;
            }
            IDEBUG("[PASS] %s: mapping resource node %s\n", __func__, fpga_resource_nodes[i]);
        }
        Py_RETURN_TRUE;
    } else {
        if (index >= MAX_FPGAS) {
            PyErr_SetString(PyExc_IndexError, "FPGA index out of range");
            return NULL;
        }
        if (hw_handle[index] != -1 && io_base[index] && io_base[index] != MAP_FAILED) {
            Py_RETURN_TRUE;
        }

        hw_handle[index] = open(fpga_resource_nodes[index], O_RDWR | O_SYNC);
        if (hw_handle[index] == -1) {
            IDEBUG("[ERROR] %s: open hw resource node %s\n", __func__, fpga_resource_nodes[index]);
            Py_RETURN_FALSE;
        }
        IDEBUG("[PASS] %s: open hw resource node %s\n", __func__, fpga_resource_nodes[index]);

        io_base[index] = mmap(NULL, FPGA_RESOURCE_LENGTH, PROT_READ | PROT_WRITE, MAP_SHARED | MAP_NORESERVE, hw_handle[index], 0);
        if (io_base[index] == MAP_FAILED) {
            IDEBUG("[ERROR] %s: mapping resource node %s\n", __func__, fpga_resource_nodes[index]);
            perror("map_failed");
            fprintf(stderr, "%d %s\n", errno, strerror(errno));
            close(hw_handle[index]); hw_handle[index] = -1;
            Py_RETURN_FALSE;
        }
        IDEBUG("[PASS] %s: mapping resource node %s\n", __func__, fpga_resource_nodes[index]);
        Py_RETURN_TRUE;
    }
}

static PyObject *fbfpgaio_hw_release(PyObject *self, PyObject *args)
{
    unsigned int index = MAX_FPGAS; /* sentinel = release all */
    if (!PyArg_ParseTuple(args, "|I", &index)) {
        return NULL;
    }

    if (index == MAX_FPGAS) {
        for (unsigned int i = 0; i < MAX_FPGAS; i++) {
            if ((io_base[i] != NULL) && (io_base[i] != MAP_FAILED)) {
                if (munmap(io_base[i], FPGA_RESOURCE_LENGTH) == 0) {
                    IDEBUG("[PASS] %s: Unmapping hardware resources %s\n", __func__, fpga_resource_nodes[i]);
                    close(hw_handle[i]);
                    io_base[i] = NULL;
                    hw_handle[i] = -1;
                }
            }
        }
        Py_RETURN_TRUE;
    } else {
        if (index >= MAX_FPGAS) {
            PyErr_SetString(PyExc_IndexError, "FPGA index out of range");
            return NULL;
        }
        if ((io_base[index] != NULL) && (io_base[index] != MAP_FAILED)) {
            if (munmap(io_base[index], FPGA_RESOURCE_LENGTH) == 0) {
                IDEBUG("[PASS] %s: Unmapping hardware resources %s\n", __func__, fpga_resource_nodes[index]);
                close(hw_handle[index]);
                io_base[index] = NULL;
                hw_handle[index] = -1;
                Py_RETURN_TRUE;
            }
        }
        IDEBUG("[ERROR] %s: unmapping resource node %s\n", __func__, fpga_resource_nodes[index]);
        Py_RETURN_FALSE;
    }
}

static PyObject *fbfpgaio_hw_io(PyObject *self, PyObject *args)
{
    unsigned int index;
    unsigned int offset;
    unsigned long input_data = 0x1FFFFFFFF;

    if (!PyArg_ParseTuple(args, "II|k", &index, &offset, &input_data)) {
        return NULL;
    }

    if (index >= MAX_FPGAS) {
        PyErr_SetString(PyExc_IndexError, "FPGA index out of range");
        return NULL;
    }

    if (io_base[index] == NULL || io_base[index] == MAP_FAILED) {
        PyErr_SetString(PyExc_RuntimeError, "FPGA not initialized");
        return NULL;
    }

    if (input_data == 0x1FFFFFFFF) {
        /* Read operation */
        unsigned int *address = (unsigned int *) ((unsigned long) io_base[index] + (unsigned long) offset);
        return Py_BuildValue("k", *address);
    } else {
        /* Write operation */
        unsigned int *address = (unsigned int *) ((unsigned long) io_base[index] + (unsigned long) offset);
        unsigned int data = (unsigned int) (input_data & 0xFFFFFFFF);
        *address = data;

        Py_INCREF(Py_None);
        return Py_None;
    }
}

static PyMethodDef FbfpgaMethods[] = {
  { "hw_init", (PyCFunction) fbfpgaio_hw_init, METH_VARARGS, "Initialize resources for accessing FPGA. hw_init([index])" },
  { "hw_release", (PyCFunction) fbfpgaio_hw_release, METH_VARARGS, "Release resources for accessing FPGA. hw_release([index])" },
  { "hw_io", fbfpgaio_hw_io, METH_VARARGS, "Access FPGA: hw_io(index, offset[, data])" },
  { NULL, NULL, 0, NULL },
};

static char docstr[] = "\
1. hw_init():\n\
   return value: True/False\n\
2. hw_release():\n\
   return value: True/False\n\
3. hw_io(index,offset,[data])\n\
   return value:\n\
     In reading operation: data which is read from FPGA\n\
     In writing operation: None\n";

static struct PyModuleDef FbfpgaModule =
{
    PyModuleDef_HEAD_INIT,
    "fbfpgaio", /* name of module */
    docstr,
    -1,   /* size of per-interpreter state of the module, or -1 if the module keeps state in global variables. */
    FbfpgaMethods
};

PyMODINIT_FUNC
PyInit_fbfpgaio(void)
{
  return PyModule_Create(&FbfpgaModule);
}


